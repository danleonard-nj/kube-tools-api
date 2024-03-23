from typing import List

from domain.bank import (PlaidBalanceRequest, PlaidTransactionRequestOptions,
                         PlaidTransactionsRequest)
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from httpx import AsyncClient

logger = get_logger(__name__)


class PlaidClient:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient
    ):
        self._base_url = configuration.plaid.get('base_url')
        self._client_id = configuration.plaid.get('client_id')
        self._client_secret = configuration.plaid.get('client_secret')

        self._http_client = http_client

        ArgumentNullException.if_none_or_whitespace(
            self._base_url, 'base_url')
        ArgumentNullException.if_none_or_whitespace(
            self._client_id, 'client_id')
        ArgumentNullException.if_none_or_whitespace(
            self._client_secret, 'client_secret')
        ArgumentNullException.if_none_or_whitespace(
            self._http_client, 'http_client')

    async def get_balance(
        self,
        access_token: str
    ):
        ArgumentNullException.if_none_or_whitespace(
            access_token, 'access_token')

        logger.info(f'Get balance w/ access token: {access_token}')

        endpoint = f'{self._base_url}/accounts/balance/get'

        # Create the request to fetch a balance for a
        # given institution as defined by the access token
        balance_request = PlaidBalanceRequest(
            client_id=self._client_id,
            secret=self._client_secret,
            access_token=access_token)

        response = await self._http_client.post(
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
        ArgumentNullException.if_none_or_whitespace(
            access_token, 'access_token')
        ArgumentNullException.if_none_or_whitespace(
            start_date, 'start_date')
        ArgumentNullException.if_none_or_whitespace(
            end_date, 'end_date')

        logger.info(
            f'Get account transactions w/ access token: {access_token}')

        endpoint = f'{self._base_url}/transactions/get'

        # Create the request to fetch transactions for a
        # given institution as defined by the access token
        options = PlaidTransactionRequestOptions(
            count=max_results,
            account_ids=account_ids,
            include_personal_finance_category=include_personal_finance_category)

        transactions_request = PlaidTransactionsRequest(
            client_id=self._client_id,
            secret=self._client_secret,
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
            options=options)

        response = await self._http_client.post(
            url=endpoint,
            json=transactions_request.to_dict())

        logger.info(f'Status: {response.status_code}')

        return response.json()
