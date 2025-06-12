from clients.coinbase_client import CoinbaseClient
from framework.logger import get_logger
from models.coinbase_models import CoinbaseAccount, CoinbaseConfig

logger = get_logger(__name__)


class CoinbaseService:
    def __init__(
        self,
        coinbase_client: CoinbaseClient,
        config: CoinbaseConfig
    ):
        self._coinbase_client = coinbase_client
        self._currencies = config.currencies

    async def get_exchange_rates(
        self
    ) -> dict[str, float]:
        exchanges = dict()

        # TODO: Fetch asynchronously w/ task collection
        for currency in self._currencies:
            # Fetch USD exchange rates for currency
            exchanges[currency] = float(await self._coinbase_client.get_usd_exchange_rate(
                currency=currency))
        return exchanges

    async def get_accounts(
        self
    ) -> list[CoinbaseAccount]:

        logger.info(f'Getting accounts from coinbase for currencies: {self._currencies}')

        result = self._coinbase_client.get_accounts()

        account_data = result.get('accounts', [])

        accounts: list[CoinbaseAccount] = []
        for account in account_data:
            accounts.append(CoinbaseAccount.model_validate(account))

        accounts = [CoinbaseAccount.model_validate(account) for account in account_data if account.get('currency') in self._currencies]
        results: list[CoinbaseAccount] = []
        exchanges = await self.get_exchange_rates()

        for account in accounts:
            exchange = exchanges.get(account.currency)
            usd_amount = account.available_balance.parsed_balance * exchange
            account.usd_exchange = exchange
            account.usd_amount = usd_amount
            account.balance = account.available_balance.parsed_balance

        return accounts
