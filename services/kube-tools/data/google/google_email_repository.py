from framework.mongo.mongo_repository import MongoRepositoryAsync
from pymongo import AsyncMongoClient

from domain.mongo import MongoCollection, MongoDatabase


class GoogleEmailRuleRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncMongoClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.Google,
            collection=MongoCollection.EmailRule)
