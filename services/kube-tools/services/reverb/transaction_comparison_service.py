from typing import List, Tuple

from framework.concurrency import TaskCollection
from framework.logger import get_logger
from framework.validators.nulls import none_or_whitespace

from clients.reverb_client import ReverbClient
from data.reverb_service_repositories import ProductTransactionRepository
from domain.reverb.comparisons import (ReverbComparison,
                                       ReverbComparisonTransaction)
from domain.reverb.product import ReverbProduct
from domain.reverb.rest import TransactionSyncResult
from services.reverb.condition_service import ReverbProductConditionService

logger = get_logger(__name__)


class ReverbTransactionComparisonService:
    def __init__(
        self,
        reverb_client: ReverbClient,
        repository: ProductTransactionRepository,
        product_condition_service: ReverbProductConditionService
    ):
        self.__reverb_client = reverb_client
        self.__repository = repository
        self.__condition_service = product_condition_service

    async def get_comparison_shopping_page(
        self,
        link: dict
    ) -> ReverbComparison:

        link_uri = link.get('href')
        response = await self.__reverb_client.from_link(
            link=link_uri)

        comparison = ReverbComparison.from_response(
            data=response)

        return comparison

    async def get_transactions_by_product_condition(
        self,
        product_id,
        condition_id
    ):
        entities = await self.__repository.get_transactions_by_product_condition(
            product_id=product_id,
            condition_id=condition_id)

        if any(entities):
            return [ReverbComparisonTransaction.from_entity(
                data=entity
            ) for entity in entities]

        return list()

    async def get_transactions_keys(
        self,
        product_id: str
    ) -> Tuple[List[ReverbComparisonTransaction], List[str]]:

        existing_transactions = await self.__repository.get_transactions(
            product_id=product_id)

        transactions = [ReverbComparisonTransaction.from_entity(
            data=existing_transaction
        ) for existing_transaction in existing_transactions]

        logger.info(
            f'Fetched {len(existing_transactions)} existing transactions for product {product_id}')

        transaction_keys = [
            transaction.get_key()
            for transaction in transactions
        ]

        return (transactions, transaction_keys)

    async def sync_transaction(self, transaction: ReverbComparisonTransaction):
        condition = await self.__condition_service.get_condition_by_key(
            condition_bk=transaction
        )

    async def sync_transactions(
        self,
        product: ReverbProduct
    ) -> TransactionSyncResult:

        if none_or_whitespace(product.product_bk):
            raise Exception('Product BK cannot be null')

        response = await self.__reverb_client.get_comparison_transactions(
            slug=product.product_bk)

        response_transactions = response.get('transactions')

        transactions = []
        for transaction in response_transactions:
            condition = await self.__condition_service.get_condition_by_name(
                condition_name=transaction.get('condition'))

            model = ReverbComparisonTransaction.from_response(
                data=transaction,
                product_id=product.product_id,
                product_condition_id=condition.condition_id)
            transactions.append(model)

        existing_transactions, existing_keys = await self.get_transactions_keys(
            product_id=product.product_id)

        synced_transactions = []
        sync_tasks = TaskCollection()

        for transaction in transactions:
            key = transaction.get_key()

            if key not in existing_keys:
                sync_tasks.add_task(self.__repository.insert(
                    document=transaction.to_dict()))

                synced_transactions.append(transaction)

        if any(synced_transactions):
            await sync_tasks.run()

        return TransactionSyncResult(
            existing=existing_transactions,
            synced=synced_transactions)
