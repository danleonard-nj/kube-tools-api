from typing import Optional

from framework.logger import get_logger
from httpx import AsyncClient

logger = get_logger(__name__)

YAHOO_CHART_URL = 'https://query1.finance.yahoo.com/v8/finance/chart'
_HEADERS = {'User-Agent': 'Mozilla/5.0'}


class StockQuoteClient:
    def __init__(self, http_client: AsyncClient):
        self._http_client = http_client

    async def _fetch_chart(self, ticker: str, range_str: str, interval: str) -> Optional[dict]:
        """Shared Yahoo Finance chart fetch. Returns the first result node or None."""
        url = f'{YAHOO_CHART_URL}/{ticker}'
        response = await self._http_client.get(
            url=url,
            params={'range': range_str, 'interval': interval},
            headers=_HEADERS)

        if response.status_code != 200:
            logger.error(f'{ticker}: Yahoo Finance returned {response.status_code}')
            return None

        results = response.json().get('chart', {}).get('result')
        if not results:
            logger.error(f'{ticker}: empty chart result')
            return None

        return results[0]

    async def get_current_price(self, ticker: str) -> Optional[dict]:
        """Returns current price, session open, and previous close for a ticker.

        Keys: price, market_open, previous_close.  Returns None on failure.
        """
        result = await self._fetch_chart(ticker, range_str='1d', interval='1m')
        if result is None:
            return None

        meta = result.get('meta', {})
        price = meta.get('regularMarketPrice')
        if price is None:
            logger.error(f'{ticker}: regularMarketPrice missing from meta')
            return None

        market_open = meta.get('regularMarketOpen')
        previous_close = meta.get('chartPreviousClose') or meta.get('previousClose')

        # Yahoo occasionally omits regularMarketOpen from meta; fall back to
        # the first value in the intraday open series.
        if market_open is None:
            opens = result.get('indicators', {}).get('quote', [{}])[0].get('open', [])
            market_open = next((v for v in opens if v is not None), None)

        logger.info(
            f'{ticker}: price={price}, market_open={market_open}, previous_close={previous_close}')

        return {
            'price': float(price),
            'market_open': float(market_open) if market_open is not None else None,
            'previous_close': float(previous_close) if previous_close is not None else None,
        }

    async def get_history_bars(
        self,
        ticker: str,
        range_str: str = '5d',
        interval: str = '5m'
    ) -> list[dict]:
        """Returns historical bars for backfill as a list of {ts, close} dicts."""
        result = await self._fetch_chart(ticker, range_str=range_str, interval=interval)
        if result is None:
            return []

        timestamps = result.get('timestamp', [])
        closes = result.get('indicators', {}).get('quote', [{}])[0].get('close', [])

        bars = [
            {'ts': ts, 'close': float(close)}
            for ts, close in zip(timestamps, closes)
            if close is not None
        ]

        logger.info(f'{ticker}: fetched {len(bars)} history bars (range={range_str}, interval={interval})')
        return bars
