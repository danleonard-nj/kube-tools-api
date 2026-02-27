import io
from datetime import datetime, timedelta, time
from typing import Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import pytz

from clients.sib_client import SendInBlueClient
from clients.storage_client import StorageClient
from clients.stock_quote_client import StockQuoteClient
from data.stock_monitor_repository import (StockAlertStateRepository,
                                           StockTickRepository)
from domain.stock_monitor import (ET, MARKET_CLOSE, MARKET_OPEN, AlertType,
                                  MarketSession, get_market_session)
from framework.logger import get_logger
from models.stock_monitor_config import StockMonitorConfig

logger = get_logger(__name__)


class StockMonitorService:
    CHART_CONTAINER = 'stock-charts'

    def __init__(
        self,
        stock_quote_client: StockQuoteClient,
        tick_repository: StockTickRepository,
        alert_state_repository: StockAlertStateRepository,
        sib_client: SendInBlueClient,
        storage_client: StorageClient,
        config: StockMonitorConfig
    ):
        self._quote_client = stock_quote_client
        self._tick_repo = tick_repository
        self._alert_repo = alert_state_repository
        self._sib_client = sib_client
        self._storage = storage_client
        self._config = config
        self._indexes_ensured = False

    async def _ensure_indexes(self):
        if not self._indexes_ensured:
            await self._tick_repo.ensure_indexes()
            await self._alert_repo.ensure_indexes()
            self._indexes_ensured = True

    async def poll(
        self,
        sell_threshold: Optional[float] = None,
        floor_threshold: Optional[float] = None,
        swing_percent: Optional[float] = None
    ) -> dict:
        """Main poll entrypoint. Thresholds from request override config defaults."""

        sell_threshold = sell_threshold if sell_threshold is not None else self._config.sell_threshold
        floor_threshold = floor_threshold if floor_threshold is not None else self._config.floor_threshold
        swing_percent = swing_percent if swing_percent is not None else self._config.swing_percent
        ticker = self._config.ticker

        await self._ensure_indexes()

        now_utc = datetime.utcnow()
        now_et = datetime.now(ET)

        # 1) Fetch current price
        current_price = await self._quote_client.get_current_price(ticker)
        if current_price is None:
            logger.error(f'Failed to fetch price for {ticker}')
            return {
                'ticker': ticker,
                'ts': now_et.isoformat(),
                'error': 'Failed to fetch current price',
                'triggered_events': [],
            }

        market_session = get_market_session(now_et)

        # 2) Persist current tick
        tick_doc = {
            'ticker': ticker,
            'ts': now_utc,
            'price': current_price,
            'source': 'yahoo_finance',
            'market_session': market_session.value,
        }
        await self._tick_repo.upsert_tick(tick_doc)
        logger.info(f'Persisted tick: {ticker}={current_price} session={market_session.value}')

        # 3) Backfill if needed
        since_24h_utc = now_utc - timedelta(hours=24)
        sample_count = await self._tick_repo.count_ticks_since(ticker, since_24h_utc)

        if sample_count < self._config.backfill_min_samples:
            logger.info(f'Backfill needed: only {sample_count} samples in last 24h')
            await self._backfill(ticker, now_utc)

        # 4) Compute 24h window metrics
        ticks_24h = await self._tick_repo.get_ticks_since(ticker, since_24h_utc)
        metrics = self._compute_metrics(ticks_24h)
        sample_count_24h = len(ticks_24h)

        # 5) Evaluate alerts
        session_open_price = None
        intraday_move_percent = None
        triggered_events = []

        # SELL alert
        sell_events = await self._evaluate_sell(
            ticker, current_price, sell_threshold)
        triggered_events.extend(sell_events)

        # FLOOR alert
        floor_events = await self._evaluate_floor(
            ticker, current_price, floor_threshold)
        triggered_events.extend(floor_events)

        # SWING alert (regular hours only)
        if market_session == MarketSession.REGULAR:
            swing_result = await self._evaluate_swing(
                ticker, current_price, swing_percent, now_et, now_utc)
            triggered_events.extend(swing_result['events'])
            session_open_price = swing_result.get('session_open_price')
            intraday_move_percent = swing_result.get('intraday_move_percent')

        # 6 + 7) If any alerts triggered, generate charts and send email
        if triggered_events:
            logger.info(f'Alerts triggered for {ticker}: {triggered_events}')

            # Fetch 3-day ticks for the history chart
            since_3d_utc = now_utc - timedelta(days=3)
            ticks_3d = await self._tick_repo.get_ticks_since(ticker, since_3d_utc)

            # Chart 1: Today's session (9:30 ET forward)
            today_chart_bytes = self._generate_today_session_chart(
                ticks_24h, ticker, sell_threshold, floor_threshold,
                current_price, now_et)

            # Chart 2: Last 3 days (regular sessions only)
            history_chart_bytes = self._generate_3day_chart(
                ticks_3d, ticker, sell_threshold, floor_threshold,
                current_price)

            # Upload charts to Azure Blob Storage
            ts_slug = now_et.strftime('%Y%m%d_%H%M%S')
            today_chart_url = await self._storage.upload_blob_with_url(
                container_name=self.CHART_CONTAINER,
                blob_name=f'{ticker.lower()}/{ts_slug}_today.png',
                blob_data=today_chart_bytes,
                content_type='image/png')

            history_chart_url = await self._storage.upload_blob_with_url(
                container_name=self.CHART_CONTAINER,
                blob_name=f'{ticker.lower()}/{ts_slug}_3day.png',
                blob_data=history_chart_bytes,
                content_type='image/png')

            await self._send_alert_email(
                ticker=ticker,
                current_price=current_price,
                triggered_events=triggered_events,
                now_et=now_et,
                metrics=metrics,
                session_open_price=session_open_price,
                intraday_move_percent=intraday_move_percent,
                sell_threshold=sell_threshold,
                floor_threshold=floor_threshold,
                swing_percent=swing_percent,
                today_chart_url=today_chart_url,
                history_chart_url=history_chart_url)

        # 8) Return telemetry
        return {
            'ticker': ticker,
            'ts': now_et.isoformat(),
            'current_price': current_price,
            'triggered_events': triggered_events,
            'intraday_move_percent': intraday_move_percent,
            'session_open_price': session_open_price,
            'high_24h': metrics['high_24h'],
            'low_24h': metrics['low_24h'],
            'sample_count_24h': sample_count_24h,
            'market_session': market_session.value,
            'sell_threshold': sell_threshold,
            'floor_threshold': floor_threshold,
            'swing_percent': swing_percent,
        }

    # ── Backfill ────────────────────────────────────────────

    async def _backfill(self, ticker: str, now_utc: datetime):
        """Fetch 5-day/5-min bars and upsert into Mongo."""
        bars = await self._quote_client.get_history_bars(
            ticker, range_str='5d', interval='5m')

        if not bars:
            logger.warning(f'No backfill bars returned for {ticker}')
            return

        docs = []
        for bar in bars:
            bar_utc = datetime.utcfromtimestamp(bar['ts'])
            bar_et = datetime.fromtimestamp(bar['ts'], tz=ET)
            docs.append({
                'ticker': ticker,
                'ts': bar_utc,
                'price': bar['close'],
                'source': 'yahoo_finance_backfill',
                'market_session': get_market_session(bar_et).value,
            })

        await self._tick_repo.upsert_many_ticks(docs)
        logger.info(f'Backfilled {len(docs)} bars for {ticker}')

    # ── Metrics ─────────────────────────────────────────────

    @staticmethod
    def _compute_metrics(ticks: list[dict]) -> dict:
        if not ticks:
            return {
                'high_24h': None,
                'low_24h': None,
                'first_ts_24h': None,
                'last_ts_24h': None,
            }
        prices = [t['price'] for t in ticks]
        return {
            'high_24h': max(prices),
            'low_24h': min(prices),
            'first_ts_24h': ticks[0]['ts'].isoformat() if ticks else None,
            'last_ts_24h': ticks[-1]['ts'].isoformat() if ticks else None,
        }

    # ── Alert evaluation ────────────────────────────────────

    async def _evaluate_sell(
        self, ticker: str, price: float, threshold: float
    ) -> list[str]:
        state = await self._alert_repo.get_alert_state(ticker, AlertType.SELL.value)
        is_triggered = state.get('is_triggered', False) if state else False

        if price >= threshold and not is_triggered:
            await self._alert_repo.set_triggered(ticker, AlertType.SELL.value)
            logger.info(f'{ticker} SELL alert triggered at {price} (threshold {threshold})')
            return [f'SELL threshold (${threshold}) crossed -- now ${price:.2f}']
        elif price < threshold and is_triggered:
            await self._alert_repo.reset_alert(ticker, AlertType.SELL.value)
            logger.info(f'{ticker} SELL alert reset (price {price} below {threshold})')
        return []

    async def _evaluate_floor(
        self, ticker: str, price: float, threshold: float
    ) -> list[str]:
        state = await self._alert_repo.get_alert_state(ticker, AlertType.FLOOR.value)
        is_triggered = state.get('is_triggered', False) if state else False

        if price <= threshold and not is_triggered:
            await self._alert_repo.set_triggered(ticker, AlertType.FLOOR.value)
            logger.info(f'{ticker} FLOOR alert triggered at {price} (threshold {threshold})')
            return [f'FLOOR threshold (${threshold}) crossed -- now ${price:.2f}']
        elif price > threshold and is_triggered:
            await self._alert_repo.reset_alert(ticker, AlertType.FLOOR.value)
            logger.info(f'{ticker} FLOOR alert reset (price {price} above {threshold})')
        return []

    async def _evaluate_swing(
        self,
        ticker: str,
        price: float,
        swing_pct: float,
        now_et: datetime,
        now_utc: datetime
    ) -> dict:
        result = {'events': [], 'session_open_price': None, 'intraday_move_percent': None}

        # Only evaluate on weekdays during regular hours
        if now_et.weekday() >= 5:
            return result
        if not (MARKET_OPEN <= now_et.time() < MARKET_CLOSE):
            return result

        # Build today's session start in UTC
        session_start_et = now_et.replace(
            hour=9, minute=30, second=0, microsecond=0)
        session_start_utc = session_start_et.astimezone(pytz.utc).replace(tzinfo=None)

        open_tick = await self._tick_repo.get_session_open_tick(
            ticker, session_start_utc)

        if not open_tick:
            logger.warning(f'No session open tick found for {ticker}')
            return result

        session_open_price = open_tick['price']
        result['session_open_price'] = session_open_price

        if session_open_price == 0:
            return result

        move_pct = (price - session_open_price) / session_open_price
        result['intraday_move_percent'] = round(move_pct, 5)

        if abs(move_pct) < swing_pct:
            return result

        direction = AlertType.SWING_UP if move_pct > 0 else AlertType.SWING_DOWN
        trading_day = now_et.strftime('%Y-%m-%d')

        state = await self._alert_repo.get_alert_state(ticker, direction.value)
        is_triggered = state.get('is_triggered', False) if state else False
        state_day = state.get('trading_day') if state else None

        # Allow one alert per direction per trading day
        if is_triggered and state_day == trading_day:
            return result

        await self._alert_repo.set_triggered(
            ticker, direction.value, trading_day=trading_day)

        pct_str = f'{move_pct:+.1%}'
        event_str = f'Intraday swing {pct_str} -- now ${price:.2f} (open ${session_open_price:.2f})'
        result['events'].append(event_str)
        logger.info(f'{ticker} {direction.value} alert: {event_str}')

        return result

    # ── Chart generation ────────────────────────────────────

    @staticmethod
    def _generate_today_session_chart(
        ticks: list[dict],
        ticker: str,
        sell_threshold: float,
        floor_threshold: float,
        current_price: float,
        now_et: datetime
    ) -> bytes:
        """Chart 1: Today's regular session only (9:30 AM ET forward)."""

        fig, ax = plt.subplots(figsize=(8, 4))

        today_str = now_et.strftime('%m/%d')
        session_start_et = now_et.replace(
            hour=9, minute=30, second=0, microsecond=0)

        if ticks:
            session_ticks = []
            for t in ticks:
                ts_et = pytz.utc.localize(t['ts']).astimezone(ET)
                if ts_et >= session_start_et:
                    session_ticks.append({
                        'ts_et': ts_et,
                        'price': t['price']
                    })

            if session_ticks:
                times = [t['ts_et'] for t in session_ticks]
                prices = [t['price'] for t in session_ticks]
                ax.plot(times, prices, color='#1f77b4', linewidth=1.3, label=ticker)

        ax.axhline(y=sell_threshold, color='#d62728', linestyle='--',
                    linewidth=1, label=f'Sell ${sell_threshold:.0f}')
        ax.axhline(y=floor_threshold, color='#2ca02c', linestyle='--',
                    linewidth=1, label=f'Floor ${floor_threshold:.0f}')

        ax.set_title(f'{ticker} Today {today_str} (current ${current_price:.2f})',
                      fontsize=11, fontweight='bold')
        ax.set_xlabel('Time (ET)', fontsize=9)
        ax.set_ylabel('Price ($)', fontsize=9)
        ax.legend(fontsize=8, loc='upper left')
        ax.grid(True, alpha=0.3)

        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        fig.autofmt_xdate(rotation=30, ha='right')
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100)
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    @staticmethod
    def _generate_3day_chart(
        ticks: list[dict],
        ticker: str,
        sell_threshold: float,
        floor_threshold: float,
        current_price: float
    ) -> bytes:
        """Chart 2: Last 3 trading days, regular session only (9:30-16:00 ET).

        Sessions are rendered gapless (no overnight gaps). Today's line is
        thicker/full opacity while prior days are thinner/muted. Vertical
        separators mark session boundaries.
        """

        now_et = datetime.now(ET)
        today_date = now_et.date()

        # ── 1. Convert ticks to ET and filter to regular session only ──
        session_map: dict[str, list] = {}  # date_str -> [(ts_et, price)]

        if ticks:
            for t in ticks:
                ts_et = pytz.utc.localize(t['ts']).astimezone(ET)
                if ts_et.weekday() >= 5:
                    continue
                if not (MARKET_OPEN <= ts_et.time() <= MARKET_CLOSE):
                    continue
                d_str = ts_et.strftime('%Y-%m-%d')
                session_map.setdefault(d_str, []).append(
                    (ts_et, t['price']))

        # Sort sessions chronologically, take last 3
        sorted_dates = sorted(session_map.keys())
        if len(sorted_dates) > 3:
            sorted_dates = sorted_dates[-3:]

        # ── 2. Build gapless x-axis ──
        # Each session gets a contiguous block on a synthetic x-axis.
        # Session duration = 6.5 hours = 390 minutes.
        SESSION_MINUTES = 390
        fig, ax = plt.subplots(figsize=(8, 4))

        all_prices = []
        separator_x = []  # x positions for vertical session dividers
        label_positions = []  # (x, date_label) for x-axis labels
        today_str = today_date.strftime('%Y-%m-%d')

        for session_idx, d_str in enumerate(sorted_dates):
            pts = sorted(session_map[d_str], key=lambda p: p[0])
            if not pts:
                continue

            is_today = (d_str == today_str)
            session_start_et = pts[0][0].replace(
                hour=9, minute=30, second=0, microsecond=0)
            offset_base = session_idx * SESSION_MINUTES

            # Map each tick to a gapless x coordinate (minutes from chart start)
            xs = []
            ys = []
            for ts_et, price in pts:
                minutes_into_session = (
                    (ts_et - session_start_et).total_seconds() / 60.0)
                xs.append(offset_base + minutes_into_session)
                ys.append(price)
                all_prices.append(price)

            # Plot with emphasis on today
            color = '#1f77b4' if is_today else '#7bafd4'
            lw = 1.6 if is_today else 0.9
            alpha = 1.0 if is_today else 0.55
            ax.plot(xs, ys, color=color, linewidth=lw, alpha=alpha)

            # Session divider
            if session_idx > 0:
                line_lw = 1.2 if is_today else 0.6
                ax.axvline(x=offset_base, color='#999999',
                           linewidth=line_lw, linestyle='-', alpha=0.5)

            # Date label at session midpoint
            dt_parsed = datetime.strptime(d_str, '%Y-%m-%d')
            label = dt_parsed.strftime('%b %d')
            if is_today:
                label += ' (today)'
            label_positions.append(
                (offset_base + SESSION_MINUTES / 2, label))

        # ── 3. Threshold lines ──
        ax.axhline(y=sell_threshold, color='#d62728', linestyle='--',
                    linewidth=1, alpha=0.7, label=f'Sell ${sell_threshold:.0f}')
        ax.axhline(y=floor_threshold, color='#2ca02c', linestyle='--',
                    linewidth=1, alpha=0.7, label=f'Floor ${floor_threshold:.0f}')

        # ── 4. 3D High / Low annotation ──
        if all_prices:
            hi = max(all_prices)
            lo = min(all_prices)
            annotation = f'3D High: ${hi:.2f}\n3D Low: ${lo:.2f}'
            ax.text(0.98, 0.97, annotation,
                    transform=ax.transAxes, fontsize=8,
                    verticalalignment='top', horizontalalignment='right',
                    fontfamily='monospace',
                    bbox=dict(boxstyle='round,pad=0.3',
                              facecolor='white', edgecolor='#cccccc',
                              alpha=0.9))

        # ── 5. Axis formatting ──
        ax.set_title(f'{ticker} 3-Day Sessions (current ${current_price:.2f})',
                      fontsize=11, fontweight='bold')
        ax.set_ylabel('Price ($)', fontsize=9)
        ax.grid(True, alpha=0.2, linewidth=0.5)
        ax.legend(fontsize=8, loc='upper left')

        # Custom x-axis: date labels centered on each session
        if label_positions:
            tick_xs, tick_labels = zip(*label_positions)
            ax.set_xticks(list(tick_xs))
            ax.set_xticklabels(list(tick_labels), fontsize=8)

        # Remove minor ticks and spines for cleanliness
        ax.tick_params(axis='x', which='minor', bottom=False)
        for spine in ['top', 'right']:
            ax.spines[spine].set_visible(False)

        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100)
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    # ── Email ───────────────────────────────────────────────

    async def _send_alert_email(
        self,
        ticker: str,
        current_price: float,
        triggered_events: list[str],
        now_et: datetime,
        metrics: dict,
        session_open_price: Optional[float],
        intraday_move_percent: Optional[float],
        sell_threshold: float,
        floor_threshold: float,
        swing_percent: float,
        today_chart_url: str,
        history_chart_url: str
    ):
        # Build subject from first triggered event
        first_event = triggered_events[0] if triggered_events else ''
        subject = f'{ticker} ALERT: {first_event}'

        # Build HTML body
        events_html = ''.join(
            f'<li style="margin-bottom:4px;">{e}</li>' for e in triggered_events)

        swing_row = ''
        if session_open_price is not None and intraday_move_percent is not None:
            swing_row = f'''
            <tr><td style="padding:4px 8px;font-weight:bold;">Session Open</td>
                <td style="padding:4px 8px;">${session_open_price:.2f}</td></tr>
            <tr><td style="padding:4px 8px;font-weight:bold;">Intraday Move</td>
                <td style="padding:4px 8px;">{intraday_move_percent:+.2%}</td></tr>'''

        high_val = f'${metrics["high_24h"]:.2f}' if metrics.get('high_24h') else 'N/A'
        low_val = f'${metrics["low_24h"]:.2f}' if metrics.get('low_24h') else 'N/A'

        html_body = f'''
        <div style="font-family:Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;">
            <h2 style="color:#333;margin-bottom:4px;">{ticker} Price Alert</h2>
            <p style="color:#666;margin-top:0;">{now_et.strftime('%Y-%m-%d %I:%M %p ET')}</p>

            <h3 style="margin-bottom:6px;">Triggered Alerts</h3>
            <ul style="margin-top:0;">{events_html}</ul>

            <table style="border-collapse:collapse;width:100%;margin-bottom:16px;">
                <tr style="background:#f5f5f5;">
                    <td style="padding:4px 8px;font-weight:bold;">Current Price</td>
                    <td style="padding:4px 8px;">${current_price:.2f}</td></tr>
                <tr><td style="padding:4px 8px;font-weight:bold;">24h High</td>
                    <td style="padding:4px 8px;">{high_val}</td></tr>
                <tr style="background:#f5f5f5;">
                    <td style="padding:4px 8px;font-weight:bold;">24h Low</td>
                    <td style="padding:4px 8px;">{low_val}</td></tr>
                {swing_row}
                <tr><td style="padding:4px 8px;font-weight:bold;">Sell Threshold</td>
                    <td style="padding:4px 8px;">${sell_threshold:.2f}</td></tr>
                <tr style="background:#f5f5f5;">
                    <td style="padding:4px 8px;font-weight:bold;">Floor Threshold</td>
                    <td style="padding:4px 8px;">${floor_threshold:.2f}</td></tr>
                <tr><td style="padding:4px 8px;font-weight:bold;">Swing %</td>
                    <td style="padding:4px 8px;">{swing_percent:.1%}</td></tr>
            </table>

            <h3 style="margin-bottom:6px;">Today's Session</h3>
            <img src="{today_chart_url}" alt="{ticker} today session chart"
                 style="max-width:100%;border:1px solid #ddd;border-radius:4px;margin-bottom:16px;" />

            <h3 style="margin-bottom:6px;">Last 3 Days</h3>
            <img src="{history_chart_url}" alt="{ticker} 3-day chart"
                 style="max-width:100%;border:1px solid #ddd;border-radius:4px;" />
        </div>'''

        try:
            await self._sib_client.send_email(
                recipient=self._config.recipient_email,
                subject=subject,
                html_body=html_body,
                from_email='me@dan-leonard.com',
                from_name='KubeTools Stock Monitor')
            logger.info(f'Alert email sent for {ticker}')
        except Exception as e:
            logger.error(f'Failed to send alert email for {ticker}: {e}')
