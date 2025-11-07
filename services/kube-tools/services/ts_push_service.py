import asyncio
from datetime import datetime, timezone
import os
import time
from typing import Optional
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import feedparser
import httpx

from clients.gpt_client import GPTClient
from clients.sib_client import SendInBlueClient
from data.ts_repository import TruthSocialRepository
from framework.clients.cache_client import CacheClientAsync
from framework.clients.feature_client import FeatureClientAsync
from framework.logger import get_logger
from models.ts_models import FeedEntry, TruthSocialConfig
from services.truthsocial.email_generator import generate_truth_social_email

logger = get_logger(__name__)

CACHE_KEY_LATEST_TIMESTAMP = "truth_social_latest_timestamp"
CACHE_TTL_MINUTES = 60 * 24 * 7  # 1 week
MAX_CONCURRENT_TASKS = 12


class TruthSocialPushService:
    def __init__(
        self,
        cache_client: CacheClientAsync,
        gpt_client: GPTClient,
        config: TruthSocialConfig,
        http_client: httpx.AsyncClient,
        sib_client: SendInBlueClient,
        feature_client: FeatureClientAsync,
        ts_repository: TruthSocialRepository
    ):
        """
        :param max_concurrent_tasks: Maximum number of concurrent post processing tasks (default: 5)
        """
        self._cache_client = cache_client
        self._gpt_client = gpt_client
        self._feed_url = config.rss_feed
        self._sib_client = sib_client
        self._feature_client = feature_client
        self._recipients = config.recipients
        self._http_client = http_client
        self._ts_repository = ts_repository
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

    async def _get_gpt_model(self) -> str:
        """Get configured GPT model from feature flags."""
        model = await self._feature_client.is_enabled('gpt-model-ts-push-service')
        logger.info(f"Using GPT model: {model}")
        return model

    async def _send_email(self, recipient: str, subject: str, html_body: str) -> None:
        """Send email via SendInBlue."""
        logger.info(f"Sending email to {recipient}: '{subject}'")
        await self._sib_client.send_email(
            recipient=recipient,
            subject=subject,
            html_body=html_body,
            from_email='me@dan-leonard.com',
            from_name='TruthSocial Push'
        )
        logger.info(f"Email sent successfully to {recipient}")

    async def _summarize_post(self, content: str, model: str) -> dict:
        """Generate AI summary of post content using GPT, with semaphore for concurrency control."""
        async with self._semaphore:
            prompt = (
                f"Summarize president Donald Trump's post in a neutral, fact-based way. "
                f"Limit to 1-2 sentences, maximum 3 sentences:\n\n{content}"
            )

            start_time = time.time()
            response = await self._gpt_client.generate_response(prompt=prompt, model=model)
            generation_time = time.time() - start_time

            return {
                'summary': response.text if response else "No summary available.",
                'model': model,
                'tokens_used': response.usage if response else 0,
                'generation_time_seconds': generation_time
            }

    def _get_midnight_today_utc(self) -> int:
        """Get Unix timestamp for midnight today UTC."""
        now_utc = datetime.now(timezone.utc)
        midnight_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        return int(midnight_utc.timestamp())

    def _to_timestamp(self, published_parsed) -> int:
        """Convert feedparser's published_parsed (time.struct_time) to Unix timestamp."""
        return int(time.mktime(published_parsed))

    async def get_latest_posts(self) -> list[dict]:
        """Fetch, process, and send new Truth Social posts."""
        logger.info(f"Fetching latest posts from Truth Social feed: {self._feed_url}")

        # Get last seen timestamp from cache
        latest_timestamp = await self._cache_client.get_cache(CACHE_KEY_LATEST_TIMESTAMP)
        if not latest_timestamp:
            latest_timestamp = self._get_midnight_today_utc()
            logger.info(f"No cached timestamp found. Using midnight today UTC: {latest_timestamp}")
        else:
            latest_timestamp = int(latest_timestamp)
            logger.info(f"Last seen timestamp from cache: {latest_timestamp}")

        # Fetch and parse RSS feed
        raw_feed = feedparser.parse(self._feed_url)
        if not raw_feed.entries:
            logger.warning("No entries found in RSS feed")
            return []

        # Sort entries newest to oldest
        raw_feed.entries.sort(key=lambda e: getattr(e, "published_parsed", 0), reverse=True)

        # Validate entries
        entries = [FeedEntry.model_validate(e) for e in raw_feed.entries]
        logger.info(f"Fetched {len(entries)} total entries from feed")

        # Filter entries newer than last seen timestamp
        new_entries: list[FeedEntry] = []
        for entry in entries:
            entry_timestamp = self._to_timestamp(entry.published_parsed)
            if entry_timestamp <= latest_timestamp:
                break
            new_entries.append(entry)

        if not new_entries:
            logger.info("No new posts found since last check")
            return []

        logger.info(f"Found {len(new_entries)} new posts to process")

        # Process posts: fetch original URLs for reposts
        original_link_mapping: dict[str, str] = {}
        filtered_posts: list[FeedEntry] = []
        summary_exclude: set[str] = set()

        for post in new_entries:
            # Check if this is a repost (no title or empty summary)
            is_repost = 'No Title' in post.title or post.summary == '<p></p>'

            if is_repost:
                logger.info(f"Detected repost, fetching original URL from: {post.link}")
                try:
                    response = await self._http_client.get(post.link)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, "html.parser")

                    # Extract original URL from status details table
                    original_url = None
                    for tr in soup.select("table.status-details-table tr"):
                        key_cell = tr.find("td", class_="status-details-table__key")
                        if key_cell and key_cell.get_text(strip=True) == "Original URL":
                            val_cell = tr.find("td", class_="status-details-table__value")
                            if val_cell:
                                a = val_cell.find("a", href=True)
                                if a:
                                    original_url = a["href"]
                                    break

                    if not original_url:
                        logger.warning(f"Original URL not found for repost {post.id}, skipping")
                        continue

                    logger.info(f"Found original URL for repost: {original_url}")
                    original_link_mapping[post.id] = original_url
                    post.summary = original_url
                    post.title = f"See the original post here: {original_url}"
                    summary_exclude.add(post.id)
                    filtered_posts.append(post)

                except Exception as e:
                    logger.error(f"Failed to fetch original URL for post {post.id}: {e}")
                    continue
            else:
                filtered_posts.append(post)

        logger.info(f"Filtered to {len(filtered_posts)} posts ({len(summary_exclude)} reposts excluded from AI summary)")

        # Generate AI summaries concurrently
        summary_mapping: dict[str, dict] = {}
        posts_to_summarize = [post for post in filtered_posts if post.id not in summary_exclude]

        if posts_to_summarize:
            model = await self._get_gpt_model()
            logger.info(f"Generating AI summaries for {len(posts_to_summarize)} posts")

            summarization_tasks = [
                self._summarize_post(post.summary, model) for post in posts_to_summarize
            ]
            summaries = await asyncio.gather(*summarization_tasks, return_exceptions=True)

            # Map summaries to post IDs
            for post, summary in zip(posts_to_summarize, summaries):
                if isinstance(summary, Exception):
                    logger.error(f"Failed to summarize post {post.id}: {summary}")
                    summary_mapping[post.id] = {
                        'summary': "Summary unavailable.",
                        'model': None,
                        'tokens_used': 0,
                        'generation_time_seconds': 0
                    }
                else:
                    summary_mapping[post.id] = summary

            logger.info(f"Successfully generated {len([s for s in summaries if not isinstance(s, Exception)])} summaries")

        # Build results with summaries and metadata
        results: list[dict] = []
        posts_to_save: list[dict] = []

        for post in filtered_posts:
            post_dict = post.model_dump()
            post_timestamp = self._to_timestamp(post.published_parsed)
            summary_data = summary_mapping.get(post.id, {
                'summary': "No summary available.",
                'model': None,
                'tokens_used': 0,
                'generation_time_seconds': 0
            })

            # Add to results for email
            post_dict['ai_summary'] = summary_data['summary']
            post_dict['original_link'] = original_link_mapping.get(post.id, post.link)
            post_dict['published_timestamp'] = post_timestamp
            results.append(post_dict)

            # Prepare database record
            db_record = {
                'post_id': post.id,
                'title': post.title,
                'link': post.link,
                'original_link': original_link_mapping.get(post.id, post.link),
                'content': post.summary,
                'published_timestamp': post_timestamp,
                'ai_summary': summary_data['summary'],
                'ai_model': summary_data['model'],
                'ai_tokens_used': summary_data['tokens_used'],
                'ai_generation_time_seconds': summary_data['generation_time_seconds'],
                'is_repost': post.id in summary_exclude,
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            }
            posts_to_save.append(db_record)

        logger.info(f"Built {len(results)} post results")

        # Save posts to database
        if posts_to_save:
            try:
                logger.info(f"Saving {len(posts_to_save)} posts to database")
                for post_record in posts_to_save:
                    await self._ts_repository.upsert_post(post_record)
                logger.info("Successfully saved posts to database")
            except Exception as e:
                logger.error(f"Failed to save posts to database: {e}")

        # Send emails to recipients
        if results:
            # Determine time of day for subject line
            now_et = datetime.now(tz=ZoneInfo("America/New_York"))
            hour = now_et.hour
            time_of_day = 'morning' if hour < 12 else 'afternoon' if hour < 18 else 'evening'

            subject = self._get_email_subject(len(results), time_of_day)

            html_content = generate_truth_social_email(results)

            logger.info(f"Sending emails to {len(self._recipients)} recipients")
            for recipient in self._recipients:
                await self._send_email(recipient, subject, html_content)

            # Update cache with newest timestamp
            newest_timestamp = self._to_timestamp(entries[0].published_parsed)
            await self._cache_client.set_cache(
                CACHE_KEY_LATEST_TIMESTAMP,
                str(newest_timestamp),
                CACHE_TTL_MINUTES
            )
            logger.info(f"Updated cache with newest timestamp: {newest_timestamp}")
        else:
            logger.info("No results to send")

        return results

    def _get_email_subject(self, num_posts: int, time_of_day: str) -> str:
        """Generate email subject based on number of posts."""

        # Flag rules sent from dev environment
        env_prefix = ''
        if os.getenv('FLASK_ENV', 'production') != 'production':
            env_prefix = f"[{os.getenv('FLASK_ENV').upper()}]: "
        post_plural = 'posts' if num_posts > 1 else 'post'

        return f"{env_prefix}See {num_posts} new Truth Social {post_plural} for you this {time_of_day}!"

    async def backfill_posts(self, process_summaries: bool = True) -> dict:
        """
        Backfill database with all available posts from RSS feed.

        Args:
            process_summaries: Whether to generate AI summaries for posts (default: True).
                              Set to False to save posts without summaries for faster backfill.

        Returns:
            dict with statistics about the backfill operation
        """
        logger.info("Starting backfill operation for Truth Social posts")
        logger.info(f"Process summaries: {process_summaries}")

        # Fetch RSS feed
        raw_feed = feedparser.parse(self._feed_url)
        if not raw_feed.entries:
            logger.warning("No entries found in RSS feed for backfill")
            return {'total_entries': 0, 'new_posts': 0, 'skipped_posts': 0, 'errors': 0}

        # Sort entries newest to oldest
        raw_feed.entries.sort(key=lambda e: getattr(e, "published_parsed", 0), reverse=True)

        # Validate entries
        entries = [FeedEntry.model_validate(e) for e in raw_feed.entries]
        logger.info(f"Fetched {len(entries)} total entries from feed for backfill")

        stats = {
            'total_entries': len(entries),
            'new_posts': 0,
            'skipped_posts': 0,
            'errors': 0
        }

        # Get GPT model if processing summaries
        model = None
        if process_summaries:
            model = await self._get_gpt_model()

        # Process each entry
        for entry in entries:
            try:
                # Check if post already exists
                if await self._ts_repository.post_exists(entry.id):
                    logger.info(f"Post {entry.id} already exists, skipping")
                    stats['skipped_posts'] += 1
                    continue

                post_timestamp = self._to_timestamp(entry.published_parsed)

                # Check if this is a repost
                is_repost = 'No Title' in entry.title or entry.summary == '<p></p>'
                original_link = entry.link

                if is_repost:
                    logger.info(f"Detected repost during backfill: {entry.link}")
                    try:
                        response = await self._http_client.get(entry.link)
                        response.raise_for_status()
                        soup = BeautifulSoup(response.text, "html.parser")

                        # Extract original URL
                        for tr in soup.select("table.status-details-table tr"):
                            key_cell = tr.find("td", class_="status-details-table__key")
                            if key_cell and key_cell.get_text(strip=True) == "Original URL":
                                val_cell = tr.find("td", class_="status-details-table__value")
                                if val_cell:
                                    a = val_cell.find("a", href=True)
                                    if a:
                                        original_link = a["href"]
                                        break
                    except Exception as e:
                        logger.error(f"Failed to fetch original URL during backfill for {entry.id}: {e}")

                # Generate AI summary if requested and not a repost
                summary_data = {
                    'summary': None,
                    'model': None,
                    'tokens_used': 0,
                    'generation_time_seconds': 0
                }

                if process_summaries and not is_repost:
                    try:
                        summary_data = await self._summarize_post(entry.summary, model)
                    except Exception as e:
                        logger.error(f"Failed to generate summary during backfill for {entry.id}: {e}")
                        summary_data['summary'] = "Summary generation failed."

                # Prepare database record
                db_record = {
                    'post_id': entry.id,
                    'title': entry.title,
                    'link': entry.link,
                    'original_link': original_link,
                    'content': entry.summary,
                    'published_timestamp': post_timestamp,
                    'ai_summary': summary_data['summary'],
                    'ai_model': summary_data['model'],
                    'ai_tokens_used': summary_data['tokens_used'],
                    'ai_generation_time_seconds': summary_data['generation_time_seconds'],
                    'is_repost': is_repost,
                    'created_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow()
                }

                # Save to database
                await self._ts_repository.upsert_post(db_record)
                stats['new_posts'] += 1
                logger.info(f"Saved post {entry.id} to database (backfill)")

            except Exception as e:
                logger.error(f"Error processing entry {entry.id} during backfill: {e}")
                stats['errors'] += 1

        logger.info(f"Backfill completed: {stats}")
        return stats

    async def get_saved_posts(
        self,
        limit: int = 10,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None
    ) -> dict:
        """
        Get saved Truth Social posts from database.

        Args:
            limit: Maximum number of posts to return
            start_timestamp: Start of timestamp range (Unix timestamp)
            end_timestamp: End of timestamp range (Unix timestamp)

        Returns:
            Dictionary with success status, count, and list of posts
        """
        logger.info(
            f"Getting saved posts with limit={limit}, "
            f"start_timestamp={start_timestamp}, end_timestamp={end_timestamp}"
        )

        # If both timestamps provided, get posts in range
        if start_timestamp and end_timestamp:
            posts = await self._ts_repository.get_posts_by_timestamp_range(
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                limit=limit
            )
        else:
            # Otherwise get latest posts
            posts = await self._ts_repository.get_latest_posts(limit=limit)

        # Convert MongoDB _id and datetime objects to JSON-serializable formats
        for post in posts:
            if '_id' in post:
                post['_id'] = str(post['_id'])
            if 'created_at' in post and post['created_at']:
                post['created_at'] = post['created_at'].isoformat()
            if 'updated_at' in post and post['updated_at']:
                post['updated_at'] = post['updated_at'].isoformat()

        logger.info(f"Retrieved {len(posts)} posts")

        return {
            'success': True,
            'count': len(posts),
            'posts': posts
        }

    async def get_post_by_id(self, post_id: str) -> dict:
        logger.info(f"Getting post by ID: {post_id}")

        post = await self._ts_repository.get_post_by_document_id(post_id)

        if not post:
            logger.warning(f"Post not found: {post_id}")
            return {
                'success': False,
                'error': 'Post not found'
            }

        # Convert MongoDB _id and datetime objects
        if '_id' in post:
            post['_id'] = str(post['_id'])
        if 'created_at' in post and post['created_at']:
            post['created_at'] = post['created_at'].isoformat()
        if 'updated_at' in post and post['updated_at']:
            post['updated_at'] = post['updated_at'].isoformat()

        return {
            'success': True,
            'post': post
        }
