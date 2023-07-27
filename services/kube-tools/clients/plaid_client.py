from typing import List, Union

from framework.configuration import Configuration
from framework.logger import get_logger
from httpx import AsyncClient
from framework.exceptions.nulls import ArgumentNullException

from domain.rest import PlaidBalanceRequest, PlaidTransactionRequestOptions, PlaidTransactionsRequest

logger = get_logger(__name__)


class PlaidClient:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient
    ):
        self.__base_url = configuration.plaid.get('base_url')
        self.__client_id = configuration.plaid.get('client_id')
        self.__client_secret = configuration.plaid.get('client_secret')

        self.__http_client = http_client

        ArgumentNullException.if_none_or_whitespace(
            self.__base_url, 'base_url')
        ArgumentNullException.if_none_or_whitespace(
            self.__client_id, 'client_id')
        ArgumentNullException.if_none_or_whitespace(
            self.__client_secret, 'client_secret')
        ArgumentNullException.if_none_or_whitespace(
            self.__http_client, 'http_client')

    async def get_balance(
        self,
        access_token: str
    ):
        logger.info(f'Get balance w/ access token: {access_token}')

        endpoint = f'{self.__base_url}/accounts/balance/get'

        # Create the request to fetch a balance for a
        # given institution as defined by the access token
        balance_request = PlaidBalanceRequest(
            client_id=self.__client_id,
            secret=self.__client_secret,
            access_token=access_token)

        response = await self.__http_client.post(
            url=endpoint,
            json=balance_request.to_dict())

        logger.info(f'Status: {response.status_code}')

        return response.json()

    async def get_transactions(
        self,
        access_token: str,
        start_date: str,
        end_date: str,
        account_ids: List[str] = None,
        max_results: int = 500,
        include_personal_finance_category: bool = True
    ):
        logger.info(
            f'Get account transactions w/ access token: {access_token}')

        endpoint = f'{self.__base_url}/transactions/get'

        # Create the request to fetch transactions for a
        # given institution as defined by the access token
        options = PlaidTransactionRequestOptions(
            account_ids=account_ids,
            count=max_results,
            include_personal_finance_category=include_personal_finance_category)

        transactions_request = PlaidTransactionsRequest(
            client_id=self.__client_id,
            secret=self.__client_secret,
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
            options=options)

        response = await self.__http_client.post(
            url=endpoint,
            json=transactions_request.to_dict())

        logger.info(f'Status: {response.status_code}')

        return response.json()
