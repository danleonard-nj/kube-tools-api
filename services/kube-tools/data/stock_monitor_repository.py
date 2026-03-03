from datetime import datetime
from typing import Optional

import pymongo
from framework.logger import get_logger
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient

from domain.mongo import MongoCollection, MongoDatabase

logger = get_logger(__name__)


class StockTickRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.StockMonitor,
            collection=MongoCollection.StockTicks)

    async def ensure_indexes(self):
        """Create indexes for efficient querying and idempotent upserts."""
        await self.collection.create_index(
            [('ticker', pymongo.ASCENDING), ('ts', pymongo.DESCENDING)],
            unique=True,
            name='ticker_ts_unique')
        logger.info('StockTicks indexes ensured')

    async def upsert_tick(self, doc: dict):
        """Upsert a tick by (ticker, ts) for idempotent backfill."""
        await self.collection.update_one(
            {'ticker': doc['ticker'], 'ts': doc['ts']},
            {'$set': doc},
            upsert=True)

    async def upsert_many_ticks(self, docs: list[dict]):
        """Bulk upsert ticks."""
        if not docs:
            return
        from pymongo import UpdateOne
        ops = [
            UpdateOne(
                {'ticker': d['ticker'], 'ts': d['ts']},
                {'$set': d},
                upsert=True)
            for d in docs
        ]
        result = await self.collection.bulk_write(ops, ordered=False)
        logger.info(f'Bulk upsert: inserted={result.upserted_count} modified={result.modified_count}')

    async def get_ticks_since(
        self,
        ticker: str,
        since_utc: datetime
    ) -> list[dict]:
        """Get all ticks for a ticker since a UTC datetime, ordered by ts ascending."""
        cursor = self.collection.find(
            {'ticker': ticker, 'ts': {'$gte': since_utc}},
            sort=[('ts', pymongo.ASCENDING)])
        return await cursor.to_list(length=None)

    async def count_ticks_since(
        self,
        ticker: str,
        since_utc: datetime
    ) -> int:
        return await self.collection.count_documents(
            {'ticker': ticker, 'ts': {'$gte': since_utc}})

    async def get_session_open_tick(
        self,
        ticker: str,
        session_start_utc: datetime
    ) -> Optional[dict]:
        """Get the first tick at or after session_start_utc for a ticker."""
        return await self.collection.find_one(
            {'ticker': ticker, 'ts': {'$gte': session_start_utc}},
            sort=[('ts', pymongo.ASCENDING)])


class StockAlertStateRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.StockMonitor,
            collection=MongoCollection.StockAlertState)

    async def ensure_indexes(self):
        await self.collection.create_index(
            [('ticker', pymongo.ASCENDING), ('alert_type', pymongo.ASCENDING)],
            unique=True,
            name='ticker_alert_type_unique')
        logger.info('StockAlertState indexes ensured')

    async def get_alert_state(
        self,
        ticker: str,
        alert_type: str
    ) -> Optional[dict]:
        return await self.collection.find_one(
            {'ticker': ticker, 'alert_type': alert_type})

    async def set_triggered(
        self,
        ticker: str,
        alert_type: str,
        trading_day: str = None
    ):
        update = {
            '$set': {
                'ticker': ticker,
                'alert_type': alert_type,
                'last_triggered_at': datetime.utcnow(),
            }
        }
        if trading_day:
            update['$set']['trading_day'] = trading_day

        await self.collection.update_one(
            {'ticker': ticker, 'alert_type': alert_type},
            update,
            upsert=True)
