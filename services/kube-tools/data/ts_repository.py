from typing import Optional
from framework.mongo.mongo_repository import MongoRepositoryAsync
from framework.logger import get_logger
from motor.motor_asyncio import AsyncIOMotorClient

from domain.mongo import MongoCollection, MongoDatabase


logger = get_logger(__name__)


class TruthSocialRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.TruthSocial,
            collection=MongoCollection.TruthSocialPosts)

    async def insert_post(self, post_data: dict) -> str:
        """Insert a new Truth Social post record."""
        logger.info(f"Inserting Truth Social post: {post_data.get('post_id')}")
        result = await self.collection.insert_one(post_data)
        logger.info(f"Inserted post with _id: {result.inserted_id}")
        return str(result.inserted_id)

    async def upsert_post(self, post_data: dict) -> bool:
        """Upsert a Truth Social post by post_id."""
        post_id = post_data.get('post_id')
        logger.info(f"Upserting Truth Social post: {post_id}")
        result = await self.collection.replace_one(
            {'post_id': post_id},
            post_data,
            upsert=True
        )
        logger.info(f"Upsert result: matched={result.matched_count}, modified={result.modified_count}, upserted_id={result.upserted_id}")
        return result.upserted_id is not None or result.modified_count > 0

    async def get_post_by_id(self, post_id: str) -> Optional[dict]:
        """Get a post by post_id."""
        logger.info(f"Getting post by post_id: {post_id}")
        post = await self.collection.find_one({'post_id': post_id})
        return post

    async def post_exists(self, post_id: str) -> bool:
        """Check if a post already exists in the database."""
        count = await self.collection.count_documents({'post_id': post_id}, limit=1)
        return count > 0

    async def get_posts_by_timestamp_range(
        self,
        start_timestamp: int,
        end_timestamp: int,
        limit: Optional[int] = None
    ) -> list[dict]:
        """Get posts within a timestamp range."""
        logger.info(f"Getting posts between {start_timestamp} and {end_timestamp}")
        query = {
            'published_timestamp': {
                '$gte': start_timestamp,
                '$lte': end_timestamp
            }
        }

        cursor = self.collection.find(query).sort('published_timestamp', -1)
        if limit:
            cursor = cursor.limit(limit)

        posts = await cursor.to_list(length=limit if limit else None)
        logger.info(f"Found {len(posts)} posts")
        return posts

    async def get_latest_posts(self, limit: int = 10) -> list[dict]:
        """Get the most recent posts."""
        logger.info(f"Getting latest {limit} posts")
        posts = await self.collection.find().sort('published_timestamp', -1).limit(limit).to_list(length=limit)
        logger.info(f"Found {len(posts)} posts")
        return posts

    async def get_latest_timestamp(self) -> Optional[int]:
        """Get the timestamp of the most recent post in the database."""
        logger.info("Getting latest post timestamp")
        latest_post = await self.collection.find_one(
            sort=[('published_timestamp', -1)]
        )
        if latest_post:
            timestamp = latest_post.get('published_timestamp')
            logger.info(f"Latest timestamp: {timestamp}")
            return timestamp
        logger.info("No posts found in database")
        return None

    async def bulk_insert_posts(self, posts: list[dict]) -> int:
        """Bulk insert multiple posts."""
        if not posts:
            logger.info("No posts to insert")
            return 0

        logger.info(f"Bulk inserting {len(posts)} posts")
        result = await self.collection.insert_many(posts, ordered=False)
        inserted_count = len(result.inserted_ids)
        logger.info(f"Inserted {inserted_count} posts")
        return inserted_count
