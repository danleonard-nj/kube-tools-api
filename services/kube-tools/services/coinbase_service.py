import pandas as pd
from clients.coinbase_client import CoinbaseClient
from framework.configuration import Configuration
from framework.logger import get_logger

from domain.coinbase import GROUP_BY_AGGS, CoinbaseAccount, CoinbaseBalance

logger = get_logger(__name__)


class CoinbaseService:
    def __init__(
        self,
        configuration: Configuration,
        coinbase_client: CoinbaseClient
    ):
        self._coinbase_client = coinbase_client

        self._currencies = configuration.coinbase.get('currencies', [])

    async def get_exchange_rates(
        self
    ):
        exchanges = dict()

        for currency in self._currencies:
            rates = await self._coinbase_client.get_exchange_rates(currency)

            usd_exchange = rates.get('USD')

            logger.info(f'Exchange rates for: {currency}: {usd_exchange}')

            exchanges[currency] = float(usd_exchange)

        return exchanges

    async def get_accounts(
        self
    ):
        logger.info(f'Getting accounts from coinbase for currencies: {self._currencies}')

        data = await self._coinbase_client.get_accounts()

        accounts = [CoinbaseAccount.from_coinbase_api(account)
                    for account in data.get('data', [])]

        results = []
        exchanges = await self.get_exchange_rates()

        for currency in self._currencies:
            for account in accounts:
                if account.currency_code == currency:
                    account.usd_exchange = exchanges[currency]
                    results.append(account)

        df = pd.DataFrame([x.to_dict() for x in results])
        df = df[['currency_code', 'currency_name', 'balance', 'usd_exchange', 'usd_amount']]
        df = df.groupby(['currency_code', 'currency_name']).agg(GROUP_BY_AGGS).reset_index()

        return [CoinbaseBalance.from_dict(balance)
                for balance in df.to_dict(orient='records')]
