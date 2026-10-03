from framework.mongo.mongo_repository import MongoRepositoryAsync
from pymongo import AsyncMongoClient


class AndroidNetworkDiagnosticsRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncMongoClient
    ):
        super().__init__(
            client=client,
            database='Android',
            collection='NetworkDiagnostics')
