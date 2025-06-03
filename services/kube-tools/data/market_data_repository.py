
import datetime
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient

# TODO: Implement


class MarketDataRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='MarketData',
            collection='MarketEAV')

    async def store_portfolio_snapshot(self, user_id: str, snapshot: Dict[str, Any]):
        doc = {
            "user_id": user_id,
            "type": "portfolio_snapshot",
            "timestamp": datetime.utcnow(),
            "data": snapshot
        }
        await self._db.snapshots.insert_one(doc)

    async def store_market_news(self, user_id: str, news: List[Dict[str, Any]], tag: str = "market_news"):
        doc = {
            "user_id": user_id,
            "type": tag,
            "timestamp": datetime.utcnow(),
            "data": news
        }
        await self._db.news.insert_one(doc)

    async def store_gpt_summary(self, user_id: str, summary: Dict[str, Any], tag: str = "gpt_summary"):
        doc = {
            "user_id": user_id,
            "type": tag,
            "timestamp": datetime.utcnow(),
            "data": summary
        }
        await self._db.summaries.insert_one(doc)

    # Add more methods as needed for storing sector analysis, raw articles, etc.
