from distutils.command import build
import hashlib
import hmac
import time
from framework.configuration import Configuration
from httpx import AsyncClient
from framework.logger import get_logger
from framework.utilities.url_utils import build_url
from framework.clients.cache_client import CacheClientAsync
from framework.exceptions.nulls import ArgumentNullException

from domain.cache import CacheKey

logger = get_logger(__name__)


class CoinbaseClient:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient,
        cache_client: CacheClientAsync
    ):
        self._configuration = configuration
        self._http_client = http_client
        self._cache_client = cache_client

        self._api_key = self._configuration.coinbase.get('api_key')
        self._api_secret = self._configuration.coinbase.get('api_secret')
        self._base_url = self._configuration.coinbase.get('base_url')

    def generate_hmac_signature(
        self,
        method: str,
        request_path: str,
        timestamp: str
    ) -> str:

        logger.info(f'Generating HMAC signature for {method}: {request_path}: {timestamp}')

        message = timestamp + method + request_path

        signature = hmac.new(
            self._api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256)

        digest = signature.hexdigest()

        return digest

    def get_headers(
        self,
        request_path: str,
        method: str
    ) -> dict:

        timestamp = str(int(time.time()))

        signature = self.generate_hmac_signature(
            method=method,
            request_path=request_path,
            timestamp=timestamp)

        return {
            'CB-ACCESS-KEY': self._api_key,
            'CB-ACCESS-SIGN': signature,
            'CB-ACCESS-TIMESTAMP': timestamp,
            'Content-Type': 'application/json'
        }

    async def get_accounts(
        self
    ):
        logger.info('Fetching Coinbase accounts')

        headers = self.get_headers(
            request_path='/v2/accounts',
            method='GET')

        logger.info(f'Coinbase headers: {headers}')

        response = await self._http_client.get(
            f'{self._base_url}/v2/accounts',
            headers=headers)

        logger.info(f'Coinbase status code: {response.status_code}')

        return response.json()

    async def get_exchange_rates(
        self,
        currency: str
    ):
        ArgumentNullException.if_none_or_whitespace(currency, 'currency')

        logger.info('Fetching Coinbase exchange rates')

        CacheKey.coinbase_exchange_rates(
            currency=currency)

        endpoint = build_url(
            'https://api.coinbase.com/v2/exchange-rates',
            currency=currency)

        response = await self._http_client.get(endpoint)

        logger.info(f'Coinbase status code: {response.status_code}')

        data = response.json()

        return data.get('data').get('rates')
