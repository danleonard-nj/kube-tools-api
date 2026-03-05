from typing import Optional

from framework.logger import get_logger
from httpx import AsyncClient

logger = get_logger(__name__)

YAHOO_CHART_URL = 'https://query1.finance.yahoo.com/v8/finance/chart'


class StockQuoteClient:
    def __init__(
        self,
        http_client: AsyncClient
    ):
        self._http_client = http_client

    async def get_current_price(
        self,
        ticker: str
    ) -> Optional[dict]:
        """Fetch the latest quote price and market open for a ticker.

        Returns a dict with 'price' and 'market_open' keys, or None on failure.
        """

        url = f'{YAHOO_CHART_URL}/{ticker}'
        params = {
            'range': '1d',
            'interval': '1m',
        }

        logger.info(f'Fetching current price for {ticker}')

        response = await self._http_client.get(
            url=url,
            params=params,
            headers={'User-Agent': 'Mozilla/5.0'}
        )

        if response.status_code != 200:
            logger.error(f'Yahoo Finance returned {response.status_code} for {ticker}')
            return None

        data = response.json()
        result = data.get('chart', {}).get('result')
        if not result:
            logger.error(f'No chart result for {ticker}')
            return None

        meta = result[0].get('meta', {})
        price = meta.get('regularMarketPrice')
        market_open = meta.get('regularMarketOpen')
        previous_close = meta.get('chartPreviousClose') or meta.get('previousClose')

        logger.info(f'{ticker} current price: {price}, market open: {market_open}, previous close: {previous_close}')

        if price is None:
            return None

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
        """Fetch historical OHLC bars for backfill.

        Returns list of dicts with keys: ts (unix), close (float).
        """

        url = f'{YAHOO_CHART_URL}/{ticker}'
        params = {
            'range': range_str,
            'interval': interval,
        }

        logger.info(f'Fetching history bars for {ticker} range={range_str} interval={interval}')

        response = await self._http_client.get(
            url=url,
            params=params,
            headers={'User-Agent': 'Mozilla/5.0'}
        )

        if response.status_code != 200:
            logger.error(f'Yahoo Finance history returned {response.status_code} for {ticker}')
            return []

        data = response.json()
        result = data.get('chart', {}).get('result')
        if not result:
            logger.error(f'No chart history result for {ticker}')
            return []

        timestamps = result[0].get('timestamp', [])
        closes = result[0].get('indicators', {}).get('quote', [{}])[0].get('close', [])

        bars = []
        for ts, close in zip(timestamps, closes):
            if close is not None:
                bars.append({
                    'ts': ts,
                    'close': float(close)
                })

        logger.info(f'Fetched {len(bars)} bars for {ticker}')
        return bars
