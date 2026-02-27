import asyncio
import calendar
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
from models.ts_models import (
    BackfillStats,
    FeedEntry,
    PostRecord,
    RepostMetadata,
    SummaryResult,
    TruthSocialConfig,
)
from services.truthsocial.email_generator import generate_truth_social_email

logger = get_logger(__name__)

# Cache configuration
CACHE_KEY_LATEST_TIMESTAMP = "truth_social_latest_timestamp"
CACHE_TTL_MINUTES = 60 * 24 * 7  # 1 week

# Concurrency
MAX_CONCURRENT_TASKS = 12

# Email sender defaults
DEFAULT_FROM_EMAIL = "me@dan-leonard.com"
DEFAULT_FROM_NAME = "TruthSocial Push"

# Time-of-day thresholds (Eastern Time hours)
MORNING_HOUR_END = 12
AFTERNOON_HOUR_END = 18

# GPT prompt template
SUMMARY_PROMPT_TEMPLATE = (
    "Summarize president Donald Trump's post in a neutral, fact-based way. "
    "Limit to 1-2 sentences, maximum 3 sentences:\n\n{content}"
)

# Repost detection patterns
REPOST_TITLE_MARKER = "No Title"
REPOST_EMPTY_SUMMARY = "<p></p>"


class TruthSocialPushService:
    def __init__(
        self,
        cache_client: CacheClientAsync,
        gpt_client: GPTClient,
        config: TruthSocialConfig,
        http_client: httpx.AsyncClient,
        sib_client: SendInBlueClient,
        feature_client: FeatureClientAsync,
        ts_repository: TruthSocialRepository,
    ):
        self._cache_client = cache_client
        self._gpt_client = gpt_client
        self._feed_url = config.rss_feed
        self._sib_client = sib_client
        self._feature_client = feature_client
        self._recipients = config.recipients
        self._http_client = http_client
        self._ts_repository = ts_repository
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

    # ──────────────────────────────────────────────
    # Utility helpers
    # ──────────────────────────────────────────────

    @staticmethod
    def _to_timestamp(published_parsed) -> int:
        """Convert feedparser's published_parsed (UTC time.struct_time) to Unix timestamp."""
        return int(calendar.timegm(published_parsed))

    @staticmethod
    def _get_midnight_today_utc() -> int:
        """Get Unix timestamp for midnight today UTC."""
        now_utc = datetime.now(timezone.utc)
        midnight_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        return int(midnight_utc.timestamp())

    @staticmethod
    def _is_repost(entry: FeedEntry) -> bool:
        """Detect whether a feed entry is a repost based on title/summary heuristics."""
        return REPOST_TITLE_MARKER in entry.title or entry.summary == REPOST_EMPTY_SUMMARY

    @staticmethod
    def _serialize_post(post: dict) -> dict:
        """Convert MongoDB _id and datetime fields to JSON-serializable formats."""
        if '_id' in post:
            post['_id'] = str(post['_id'])
        for field in ('created_at', 'updated_at'):
            if field in post and post[field]:
                post[field] = post[field].isoformat()
        return post

    @staticmethod
    def _get_time_of_day() -> str:
        """Get time-of-day label based on current Eastern Time."""
        hour = datetime.now(tz=ZoneInfo("America/New_York")).hour
        if hour < MORNING_HOUR_END:
            return 'morning'
        if hour < AFTERNOON_HOUR_END:
            return 'afternoon'
        return 'evening'

    @staticmethod
    def _get_email_subject(num_posts: int, time_of_day: str) -> str:
        """Generate email subject line, prefixed with env tag outside production."""
        env = os.getenv('FLASK_ENV', 'production')
        env_prefix = f"[{env.upper()}]: " if env != 'production' else ''
        post_plural = 'posts' if num_posts > 1 else 'post'
        return f"{env_prefix}See {num_posts} new Truth Social {post_plural} for you this {time_of_day}!"

    # ──────────────────────────────────────────────
    # External-call wrappers
    # ──────────────────────────────────────────────

    async def _get_gpt_model(self) -> str:
        """Get configured GPT model from feature flags."""
        model = await self._feature_client.is_enabled('gpt-model-ts-push-service')
        logger.info(f"Using GPT model: {model}")
        return model

    async def _send_email(self, recipient: str, subject: str, html_body: str) -> None:
        """Send a single email via SendInBlue."""
        logger.info(f"Sending email to {recipient}: '{subject}'")
        await self._sib_client.send_email(
            recipient=recipient,
            subject=subject,
            html_body=html_body,
            from_email=DEFAULT_FROM_EMAIL,
            from_name=DEFAULT_FROM_NAME,
        )
        logger.info(f"Email sent successfully to {recipient}")

    async def _summarize_post(self, content: str, model: str) -> SummaryResult:
        """Generate AI summary with semaphore-bounded concurrency."""
        async with self._semaphore:
            prompt = SUMMARY_PROMPT_TEMPLATE.format(content=content)

            start_time = time.time()
            response = await self._gpt_client.generate_response(prompt=prompt, model=model)
            generation_time = time.time() - start_time

            return SummaryResult(
                summary=response.text if response else "No summary available.",
                model=model,
                tokens_used=response.usage if response else 0,
                generation_time_seconds=generation_time,
            )

    async def _extract_original_url(self, post_link: str) -> Optional[str]:
        """Scrape the repost page to find the original post URL."""
        response = await self._http_client.get(post_link)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for tr in soup.select("table.status-details-table tr"):
            key_cell = tr.find("td", class_="status-details-table__key")
            if key_cell and key_cell.get_text(strip=True) == "Original URL":
                val_cell = tr.find("td", class_="status-details-table__value")
                if val_cell:
                    a = val_cell.find("a", href=True)
                    if a:
                        return a["href"]
        return None

    # ──────────────────────────────────────────────
    # Feed fetching & filtering
    # ──────────────────────────────────────────────

    def _parse_feed(self) -> list[FeedEntry]:
        """Fetch and validate RSS feed entries, sorted newest-first."""
        raw_feed = feedparser.parse(self._feed_url)
        if not raw_feed.entries:
            logger.warning("No entries found in RSS feed")
            return []

        raw_feed.entries.sort(
            key=lambda e: getattr(e, "published_parsed", 0), reverse=True
        )
        entries = [FeedEntry.model_validate(e) for e in raw_feed.entries]
        logger.info(f"Fetched {len(entries)} total entries from feed")
        return entries

    def _filter_new_entries(
        self, entries: list[FeedEntry], since_timestamp: int
    ) -> list[FeedEntry]:
        """Return entries strictly newer than *since_timestamp*."""
        new_entries: list[FeedEntry] = []
        for entry in entries:
            if self._to_timestamp(entry.published_parsed) <= since_timestamp:
                break
            new_entries.append(entry)
        logger.info(f"Found {len(new_entries)} new posts since timestamp {since_timestamp}")
        return new_entries

    # ──────────────────────────────────────────────
    # Repost resolution
    # ──────────────────────────────────────────────

    async def _resolve_reposts(
        self, entries: list[FeedEntry]
    ) -> tuple[list[FeedEntry], RepostMetadata]:
        """
        For each entry, detect reposts and resolve original URLs.
        Returns filtered entries and repost metadata.
        """
        meta = RepostMetadata()
        filtered: list[FeedEntry] = []

        for post in entries:
            if not self._is_repost(post):
                filtered.append(post)
                continue

            logger.info(f"Detected repost, fetching original URL from: {post.link}")
            try:
                original_url = await self._extract_original_url(post.link)
                if not original_url:
                    logger.warning(f"Original URL not found for repost {post.id}, skipping")
                    continue

                logger.info(f"Found original URL for repost: {original_url}")
                meta.original_link_mapping[post.id] = original_url
                meta.repost_ids.add(post.id)
                post.summary = original_url
                post.title = f"See the original post here: {original_url}"
                filtered.append(post)

            except Exception as e:
                logger.error(f"Failed to fetch original URL for post {post.id}: {e}")
                continue

        logger.info(
            f"Filtered to {len(filtered)} posts "
            f"({len(meta.repost_ids)} reposts excluded from AI summary)"
        )
        return filtered, meta

    # ──────────────────────────────────────────────
    # Summarization
    # ──────────────────────────────────────────────

    async def _summarize_entries(
        self,
        entries: list[FeedEntry],
        exclude_ids: set[str],
    ) -> dict[str, SummaryResult]:
        """Generate AI summaries concurrently, skipping excluded IDs (reposts)."""
        to_summarize = [e for e in entries if e.id not in exclude_ids]
        if not to_summarize:
            return {}

        model = await self._get_gpt_model()
        logger.info(f"Generating AI summaries for {len(to_summarize)} posts")

        tasks = [self._summarize_post(e.summary, model) for e in to_summarize]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        mapping: dict[str, SummaryResult] = {}
        success_count = 0
        for entry, result in zip(to_summarize, results):
            if isinstance(result, Exception):
                logger.error(f"Failed to summarize post {entry.id}: {result}")
                mapping[entry.id] = SummaryResult(summary="Summary unavailable.")
            else:
                mapping[entry.id] = result
                success_count += 1

        logger.info(f"Successfully generated {success_count}/{len(to_summarize)} summaries")
        return mapping

    # ──────────────────────────────────────────────
    # Record building & persistence
    # ──────────────────────────────────────────────

    def _build_post_records(
        self,
        entries: list[FeedEntry],
        summaries: dict[str, SummaryResult],
        meta: RepostMetadata,
    ) -> tuple[list[dict], list[PostRecord]]:
        """
        Build email-result dicts and typed DB records from processed entries.
        Returns (email_results, db_records).
        """
        email_results: list[dict] = []
        db_records: list[PostRecord] = []
        now = datetime.now(timezone.utc)

        for post in entries:
            ts = self._to_timestamp(post.published_parsed)
            summary = summaries.get(post.id, SummaryResult())
            original_link = meta.original_link_mapping.get(post.id, post.link)

            # Email payload (preserves existing dict shape for email_generator)
            result = post.model_dump()
            result['ai_summary'] = summary.summary
            result['original_link'] = original_link
            result['published_timestamp'] = ts
            email_results.append(result)

            # Database record
            db_records.append(PostRecord(
                post_id=post.id,
                title=post.title,
                link=post.link,
                original_link=original_link,
                content=post.summary,
                published_timestamp=ts,
                ai_summary=summary.summary,
                ai_model=summary.model,
                ai_tokens_used=summary.tokens_used,
                ai_generation_time_seconds=summary.generation_time_seconds,
                is_repost=post.id in meta.repost_ids,
                created_at=now,
                updated_at=now,
            ))

        logger.info(f"Built {len(email_results)} post results")
        return email_results, db_records

    async def _persist_posts(self, records: list[PostRecord]) -> None:
        """Save post records to the database."""
        if not records:
            return
        try:
            logger.info(f"Saving {len(records)} posts to database")
            for record in records:
                await self._ts_repository.upsert_post(record.model_dump())
            logger.info("Successfully saved posts to database")
        except Exception as e:
            logger.error(f"Failed to save posts to database: {e}")

    # ──────────────────────────────────────────────
    # Email notifications
    # ──────────────────────────────────────────────

    async def _notify_recipients(self, results: list[dict]) -> None:
        """Generate and send notification emails concurrently for new posts."""
        if not results:
            logger.info("No results to send")
            return

        subject = self._get_email_subject(len(results), self._get_time_of_day())
        html_content = generate_truth_social_email(results)

        logger.info(f"Sending emails to {len(self._recipients)} recipients")
        send_tasks = [
            self._send_email(r, subject, html_content) for r in self._recipients
        ]
        outcomes = await asyncio.gather(*send_tasks, return_exceptions=True)

        for recipient, outcome in zip(self._recipients, outcomes):
            if isinstance(outcome, Exception):
                logger.error(f"Failed to send email to {recipient}: {outcome}")

    # ──────────────────────────────────────────────
    # Cache / timestamp resolution
    # ──────────────────────────────────────────────

    async def _get_latest_timestamp(self) -> int:
        """
        Resolve the latest-seen timestamp.
        Priority: cache -> database -> midnight today UTC.
        """
        cached = await self._cache_client.get_cache(CACHE_KEY_LATEST_TIMESTAMP)
        if cached:
            ts = int(cached)
            logger.info(f"Last seen timestamp from cache: {ts}")
            return ts

        db_ts = await self._ts_repository.get_latest_timestamp()
        if db_ts is not None:
            logger.info(f"Last seen timestamp from database: {db_ts}")
            return db_ts

        midnight = self._get_midnight_today_utc()
        logger.info(f"No cached or DB timestamp found. Using midnight today UTC: {midnight}")
        return midnight

    async def _update_cache_timestamp(self, entries: list[FeedEntry]) -> None:
        """Update cache with the newest entry's timestamp."""
        if not entries:
            return
        newest = self._to_timestamp(entries[0].published_parsed)
        await self._cache_client.set_cache(
            CACHE_KEY_LATEST_TIMESTAMP,
            str(newest),
            CACHE_TTL_MINUTES,
        )
        logger.info(f"Updated cache with newest timestamp: {newest}")

    # ──────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────

    async def get_latest_posts(self) -> list[dict]:
        """Fetch, process, and send new Truth Social posts."""
        logger.info(f"Fetching latest posts from Truth Social feed: {self._feed_url}")

        latest_timestamp = await self._get_latest_timestamp()

        entries = self._parse_feed()
        if not entries:
            return []

        new_entries = self._filter_new_entries(entries, latest_timestamp)
        if not new_entries:
            logger.info("No new posts found since last check")
            return []

        filtered, meta = await self._resolve_reposts(new_entries)
        summaries = await self._summarize_entries(filtered, meta.repost_ids)
        results, db_records = self._build_post_records(filtered, summaries, meta)

        await self._persist_posts(db_records)
        await self._notify_recipients(results)
        await self._update_cache_timestamp(entries)

        return results

    async def backfill_posts(self, process_summaries: bool = True) -> dict:
        """
        Backfill database with all available posts from RSS feed.
        Returns dict with statistics about the operation.
        """
        logger.info(f"Starting backfill operation (process_summaries={process_summaries})")

        entries = self._parse_feed()
        if not entries:
            return BackfillStats().model_dump()

        stats = BackfillStats(total_entries=len(entries))

        # Filter to posts not already in DB
        new_entries: list[FeedEntry] = []
        for entry in entries:
            if await self._ts_repository.post_exists(entry.id):
                logger.info(f"Post {entry.id} already exists, skipping")
                stats.skipped_posts += 1
            else:
                new_entries.append(entry)

        if not new_entries:
            logger.info("All posts already exist in database")
            return stats.model_dump()

        # Resolve reposts using shared helper
        filtered, meta = await self._resolve_reposts(new_entries)

        # Generate summaries concurrently (if requested)
        summaries: dict[str, SummaryResult] = {}
        if process_summaries:
            summaries = await self._summarize_entries(filtered, meta.repost_ids)

        # Build and persist records
        _, db_records = self._build_post_records(filtered, summaries, meta)

        for record in db_records:
            try:
                await self._ts_repository.upsert_post(record.model_dump())
                stats.new_posts += 1
                logger.info(f"Saved post {record.post_id} to database (backfill)")
            except Exception as e:
                logger.error(f"Error saving post {record.post_id} during backfill: {e}")
                stats.errors += 1

        logger.info(f"Backfill completed: {stats.model_dump()}")
        return stats.model_dump()

    async def get_saved_posts(
        self,
        limit: int = 10,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> dict:
        """Get saved Truth Social posts from database."""
        logger.info(
            f"Getting saved posts with limit={limit}, "
            f"start_timestamp={start_timestamp}, end_timestamp={end_timestamp}"
        )

        if start_timestamp and end_timestamp:
            posts = await self._ts_repository.get_posts_by_timestamp_range(
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                limit=limit,
            )
        else:
            posts = await self._ts_repository.get_latest_posts(limit=limit)

        posts = [self._serialize_post(p) for p in posts]
        logger.info(f"Retrieved {len(posts)} posts")

        return {
            'success': True,
            'count': len(posts),
            'posts': posts,
        }

    async def get_post_by_id(self, document_id: str) -> dict:
        """Get a specific Truth Social post by document ID."""
        logger.info(f"Getting post by document ID: {document_id}")

        post = await self._ts_repository.get_post_by_document_id(document_id)

        if not post:
            logger.warning(f"Post not found: {document_id}")
            return {'success': False, 'error': 'Post not found'}

        return {
            'success': True,
            'post': self._serialize_post(post),
        }
