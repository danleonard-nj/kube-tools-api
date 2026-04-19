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
from framework.clients.feature_client import FeatureClientAsync
from models.stock_monitor_config import StockMonitorConfig

logger = get_logger(__name__)

SWING_COOLDOWN_FEATURE_KEY = 'stock-monitor-swing-cooldown'

class StockMonitorService:
    CHART_CONTAINER = 'stock-charts'

    def __init__(
        self,
        stock_quote_client: StockQuoteClient,
        tick_repository: StockTickRepository,
        alert_state_repository: StockAlertStateRepository,
        sib_client: SendInBlueClient,
        storage_client: StorageClient,
        config: StockMonitorConfig,
        feature_client: FeatureClientAsync
    ):
        self._quote_client = stock_quote_client
        self._tick_repo = tick_repository
        self._alert_repo = alert_state_repository
        self._sib_client = sib_client
        self._storage = storage_client
        self._config = config
        self._indexes_ensured = False
        self._feature_client = feature_client

    async def _get_cooldown_minutes(self) -> int:
        if result := await self._feature_client.is_enabled(SWING_COOLDOWN_FEATURE_KEY):
            try:
                cooldown = int(result)
                logger.info(f'Feature override: {SWING_COOLDOWN_FEATURE_KEY}={cooldown}')
                return cooldown
            except ValueError:
                logger.warning(f'Invalid value for {SWING_COOLDOWN_FEATURE_KEY}: {result}')
        return self._config.swing_cooldown_minutes

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
        quote = await self._quote_client.get_current_price(ticker)
        if quote is None:
            logger.error(f'Failed to fetch price for {ticker}')
            return {
                'ticker': ticker,
                'ts': now_et.isoformat(),
                'error': 'Failed to fetch current price',
                'triggered_events': [],
            }

        current_price = quote['price']
        market_open_price = quote.get('market_open')
        previous_close = quote.get('previous_close')

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

        logger.info(f'Evaluated SELL/FLOOR alerts for {ticker}: {triggered_events}')

        # SWING alert (regular hours only)
        if market_session == MarketSession.REGULAR:
            swing_result = await self._evaluate_swing(
                ticker, current_price, swing_percent, now_et, now_utc,
                market_open_price=market_open_price,
                previous_close=previous_close)
            triggered_events.extend(swing_result['events'])
            session_open_price = swing_result.get('session_open_price')
            intraday_move_percent = swing_result.get('intraday_move_percent')

            logger.info(f'Evaluated SWING alerts for {ticker}: {swing_result["events"]}')

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

    async def _within_cooldown(self, state: Optional[dict]) -> bool:
        """True if we alerted recently and should suppress."""
        if not state or not state.get('last_triggered_at'):
            logger.info('No prior alert state or timestamp, not within cooldown')
            return False
        elapsed = datetime.utcnow() - state['last_triggered_at']
        cooldown_minutes = await self._get_cooldown_minutes()
        is_within_cooldown = elapsed < timedelta(minutes=cooldown_minutes)
        if is_within_cooldown:
            logger.info(f'Alert triggered recently ({elapsed}), within cooldown ({cooldown_minutes}m): {state}')
        return is_within_cooldown

    async def _evaluate_sell(
        self, ticker: str, price: float, threshold: float
    ) -> list[str]:
        if price < threshold:
            return []

        if await self._within_cooldown(await self._alert_repo.get_alert_state(ticker, AlertType.SELL.value)):
            return []

        await self._alert_repo.set_triggered(ticker, AlertType.SELL.value)
        logger.info(f'{ticker} SELL alert triggered at {price} (threshold {threshold})')
        return [f'SELL threshold (${threshold}) crossed -- now ${price:.2f}']

    async def _evaluate_floor(
        self, ticker: str, price: float, threshold: float
    ) -> list[str]:
        if price > threshold:
            return []

        if await self._within_cooldown(await self._alert_repo.get_alert_state(ticker, AlertType.FLOOR.value)):
            return []

        await self._alert_repo.set_triggered(ticker, AlertType.FLOOR.value)
        logger.info(f'{ticker} FLOOR alert triggered at {price} (threshold {threshold})')
        return [f'FLOOR threshold (${threshold}) crossed -- now ${price:.2f}']

    async def _evaluate_swing(
        self,
        ticker: str,
        price: float,
        swing_pct: float,
        now_et: datetime,
        now_utc: datetime,
        market_open_price: Optional[float] = None,
        previous_close: Optional[float] = None
    ) -> dict:
        result = {'events': [], 'session_open_price': None, 'intraday_move_percent': None}

        logger.info(
            f'[SWING] {ticker}: price={price:.2f}, swing_pct={swing_pct:.2%}, '
            f'market_open={market_open_price}, previous_close={previous_close}, '
            f'weekday={now_et.weekday()}, time_et={now_et.time()}, '
            f'market_open_window={MARKET_OPEN}-{MARKET_CLOSE}'
        )

        # Only evaluate on weekdays during regular hours
        if now_et.weekday() >= 5:
            logger.info(f'[SWING] {ticker}: skipping -- weekend (weekday={now_et.weekday()})')
            return result
        if not (MARKET_OPEN <= now_et.time() < MARKET_CLOSE):
            logger.info(
                f'[SWING] {ticker}: skipping -- outside regular hours '
                f'(time_et={now_et.time()}, window={MARKET_OPEN}-{MARKET_CLOSE})'
            )
            return result

        # Use previous_close as the reference price so that the swing %
        # matches what everyone sees as "up/down X% today".  This also
        # handles gap-open days correctly (a stock can gap down 3% at open
        # and never cross the 1% intraday-from-open threshold even though
        # it is clearly in a significant move).
        # Fall back chain: previous_close → market_open → first polled tick.
        reference_price = previous_close

        if reference_price is None:
            logger.warning(
                f'[SWING] {ticker}: previous_close not available from API, '
                f'falling back to market_open={market_open_price}'
            )
            reference_price = market_open_price

        if reference_price is None:
            session_start_et = now_et.replace(
                hour=9, minute=30, second=0, microsecond=0)
            session_start_utc = session_start_et.astimezone(pytz.utc).replace(tzinfo=None)

            open_tick = await self._tick_repo.get_session_open_tick(
                ticker, session_start_utc)

            if not open_tick:
                logger.warning(
                    f'[SWING] {ticker}: aborting -- no previous_close, no market_open, '
                    f'and no session open tick found in DB'
                )
                return result

            reference_price = open_tick['price']
            logger.warning(
                f'[SWING] {ticker}: last-resort fallback -- using first polled tick '
                f'as reference price ({reference_price:.2f})'
            )

        result['session_open_price'] = market_open_price or reference_price

        if reference_price == 0:
            logger.warning(f'[SWING] {ticker}: aborting -- reference_price is 0')
            return result

        move_pct = (price - reference_price) / reference_price
        result['intraday_move_percent'] = round(move_pct, 5)

        logger.info(
            f'[SWING] {ticker}: reference_price={reference_price:.2f}, '
            f'move_pct={move_pct:+.4%}, threshold={swing_pct:.2%}, '
            f'passes_threshold={abs(move_pct) >= swing_pct}'
        )

        if abs(move_pct) < swing_pct:
            logger.info(
                f'[SWING] {ticker}: no alert -- move {move_pct:+.4%} '
                f'is within ±{swing_pct:.2%} threshold'
            )
            return result

        direction = AlertType.SWING_UP if move_pct > 0 else AlertType.SWING_DOWN

        alert_state = await self._alert_repo.get_alert_state(ticker, direction.value)
        logger.info(f'[SWING] {ticker}: checking cooldown for {direction.value}, state={alert_state}')

        if await self._within_cooldown(alert_state):
            logger.info(
                f'[SWING] {ticker}: suppressed -- {direction.value} alert is within cooldown'
            )
            return result

        await self._alert_repo.set_triggered(ticker, direction.value)

        pct_str = f'{move_pct:+.1%}'
        event_str = (
            f'Intraday swing {pct_str} vs prev close -- '
            f'now ${price:.2f} (prev close ${reference_price:.2f})'
        )
        result['events'].append(event_str)
        logger.info(f'[SWING] {ticker}: FIRING {direction.value} alert: {event_str}')

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
