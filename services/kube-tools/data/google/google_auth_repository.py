import datetime
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient

from utilities.utils import DateTimeUtil


class GoogleAuthRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Google',
            collection='Auth')

    async def get_client(
        self,
        client_name: str
    ) -> dict:
        data = await self.get(
            selector={
                'client_name': client_name
            })

        if data is None:
            return None

        return data

    async def set_client(
        self,
        client: dict
    ) -> None:
        # Only accept dicts, selector is always by client_name
        await self.collection.replace_one(
            filter={'client_name': client['client_name']},
            replacement=client,
            upsert=True
        )

    async def update_refresh_token(
        self,
        client_name: str,
        refresh_token: str
    ) -> None:
        await self.update(
            selector={
                'client_name': client_name
            },
            values={
                'refresh_token': refresh_token,
                "updated_date": DateTimeUtil.get_iso_date()
            })
