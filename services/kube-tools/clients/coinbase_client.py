from coinbase.rest import RESTClient
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger

from models.coinbase_models import CoinbaseConfig

logger = get_logger(__name__)


class CoinbaseRESTClient(RESTClient):
    def __init__(
        self,
        config: CoinbaseConfig
    ):
        super().__init__(
            api_key=config.name,
            api_secret=config.secret)

# TODO: Can probably remove this entirely


class CoinbaseClient:
    def __init__(self, rest_client: CoinbaseRESTClient):
        self._client = rest_client

    def get_accounts(self):
        logger.info('Fetching Coinbase accounts')
        try:
            accounts = self._client.get_accounts()
            logger.info('Successfully fetched accounts')
            return accounts
        except Exception as e:
            logger.error(f'Error fetching accounts: {e}')
            return None

    async def get_usd_exchange_rate(self, currency: str):
        ArgumentNullException.if_none_or_whitespace(currency, 'currency')
        logger.info(f'Fetching Coinbase exchange rates for {currency}')

        product = self._client.get_product(F'{currency.upper()}-USD')
        price = product['price']
        return price
