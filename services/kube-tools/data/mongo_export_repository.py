from framework.mongo.mongo_repository import MongoRepositoryAsync
from pymongo import AsyncMongoClient

from domain.mongo import MongoCollection, MongoDatabase


class MongoExportRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncMongoClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.MongoExport,
            collection=MongoCollection.MongoExportHistory)
