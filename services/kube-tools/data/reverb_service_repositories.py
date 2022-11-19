
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient
import pymongo


# reverb service

# -- Product

# -- Listing

# -- ProductRule

# -- Bid

# -- GlobalRule

# -- TransactionLog


class ProductMakeRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='ReverbService',
            collection='ProductMake')

    async def get_product_make(self, product_make):
        return await self.collection.find_one({
            'product_make': product_make
        })


class ProductRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='ReverbService',
            collection='Product')

    async def get_product_by_key(self, product_key):
        return await self.collection.find_one({
            'product_key': product_key
        })

    async def get_product(self, product_id):
        pass


class ListingRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='ReverbService',
            collection='Listing')


class ProductRuleRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='ReverbService',
            collection='ProductRule')


class ProductConditionRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='ReverbService',
            collection='ProductCondition')


class GlobalRuleRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='ReverbService',
            collection='GlobalRule')


class BidRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='ReverbService',
            collection='Bid')


class ProcessorListingRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='ReverbService',
            collection='ProcessorListing')

    async def get_listings_by_date_range(
        self,
        start_date,
        end_date
    ):
        query = {
            'created_date': {
                '$gt': start_date,
                '$lte': end_date
            }
        }

        result = self.collection.find(query)
        return await result.to_list(length=None)


class ProductTransactionRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='ReverbService',
            collection='ProductTransaction')

    async def get_transactions(self, product_id):
        query_filter = {
            'product_id': product_id
        }

        result = self.collection.find(
            query_filter).sort([('transaction_date', -1)])

        return await result.to_list(length=None)

    async def get_transactions_by_product_condition(
        self,
        product_id,
        condition_id
    ):
        query_filter = {
            'product_id': product_id,
            'product_condition_id': condition_id
        }

        result = self.collection.find(
            query_filter).sort([('transaction_date', -1)])

        return await result.to_list(length=None)


class TransactionLogRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='ReverbService',
            collection='TransactionLog')
