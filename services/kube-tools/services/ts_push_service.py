from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import feedparser
import httpx
from clients.gpt_client import GPTClient
from clients.sib_client import SendInBlueClient
from domain.gpt import GPTModel
from framework.clients.cache_client import CacheClientAsync
from framework.logger import get_logger
from models.email_config import EmailConfig
from models.ts_models import FeedEntry, TruthSocialConfig
from services.truthsocial.email_generator import generate_truth_social_email
from sib_api_v3_sdk import ApiClient
from sib_api_v3_sdk import Configuration as SibConfiguration
from sib_api_v3_sdk.api.transactional_emails_api import TransactionalEmailsApi
from sib_api_v3_sdk.models import SendSmtpEmail

logger = get_logger(__name__)

CACHE_TTL_MINUTES = 60 * 24 * 7  # 1 week


class TruthSocialPushService:
    def __init__(
        self,
        cache_client: CacheClientAsync,
        gpt_client: GPTClient,
        email_config: EmailConfig,
        config: TruthSocialConfig,
        http_client: httpx.AsyncClient,
        sib_client: SendInBlueClient
    ):
        self._cache_client = cache_client
        self._gpt_client = gpt_client
        self._feed_url = config.rss_feed
        self._sib_client = sib_client

        # sib_config = SibConfiguration()
        # sib_config.api_key['api-key'] = email_config.sendinblue_api_key.get_secret_value()
        # self._sib_client = ApiClient(sib_config)
        # self._sib_email_api = TransactionalEmailsApi(self._sib_client)
        self._recipients = config.recipients

        self._http_client = http_client

    async def _send_email_sendinblue(self, recipient: str, subject: str, html_body: str) -> None:
        """Send email via Sendinblue API."""

        await self._sib_client.send_email(
            recipient=recipient,
            subject=subject,
            html_body=html_body,
            from_email='me@dan-leonard.com',
            from_name='TruthSocial Push'
        )

        # email = SendSmtpEmail(
        #     to=[{"email": recipient}],
        #     sender={"email": 'me@dan-leonard.com', "name": "TruthSocial Push Service"},
        #     subject=subject,
        #     html_content=html_body
        # )

        # self._sib_email_api.send_transac_email(email)
        logger.info(f"Email sent successfully to {recipient}")

    async def summarize_post(self, content: str) -> str:
        """
        Summarizes the content of a post using GPT.
        """
        prompt = (
            f"Summarize Donald Trump's post in a neutral, fact-based way, "
            f"if it needs to be summarized. Try to limit to 3 sentences maximum, "
            f"shooting for 1-2 sentences:\n\n{content}"
        )
        response = await self._gpt_client.generate_completion(
            prompt=prompt,
            model=GPTModel.GPT_4O_MINI,
            max_tokens=250,
            temperature=0.5
        )
        return response.content if response else "No summary available."

    async def get_latest_posts(self) -> list[dict]:
        logger.info("Fetching latest posts from Truth Social feed...")
        cache_key = "truth_social_latest_timestamp"

        # 1. Retrieve the last seen timestamp from cache
        latest_timestamp = await self._cache_client.get_cache(cache_key)
        if not latest_timestamp:
            # Default to midnight today in New York timezone if no timestamp is cached
            midnight_today = datetime.now(ZoneInfo("America/New_York")).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            latest_timestamp = midnight_today
            logger.info(f"No cached timestamp found. Defaulting to midnight today: {latest_timestamp}")

        logger.info(f"Latest timestamp from cache: {latest_timestamp}")

        # 2a. Fetch the feed
        raw = feedparser.parse(self._feed_url)
        # 2b. Sort entries newest->oldest by published date
        raw.entries.sort(
            key=lambda e: getattr(e, "published_parsed", 0),
            reverse=True
        )
        # 2c. Wrap entries in models
        entries = [FeedEntry.model_validate(e) for e in raw.entries]
        logger.info(f"Fetched {len(entries)} entries from the feed.")

        # 3. Collect all entries newer than latest_timestamp
        new_entries: list[FeedEntry] = []
        for entry in entries:
            entry_timestamp = datetime(*entry.published_parsed[:6], tzinfo=ZoneInfo("America/New_York"))
            if latest_timestamp and entry_timestamp <= datetime.fromisoformat(latest_timestamp):
                break
            new_entries.append(entry)

        if not new_entries:
            logger.info("No new posts found since the last check.")
            return []

        # 4. Limit how many to process (e.g., avoid spamming)
        to_process = new_entries  # Process all new entries, not just the first 5
        logger.info(f"Processing {len(to_process)} new entries.")

        # 5. Fetch original URLs for 'No Title' or empty summaries
        original_link_mapping: dict[str, str] = {}
        filtered_posts: list[FeedEntry] = []
        summary_exclude: list[str] = []

        for post in to_process:
            if 'No Title' in post.title or post.summary == '<p></p>':
                logger.info(f"Fetching page content for: {post.link}")
                response = await self._http_client.get(post.link)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")

                original_url = None
                for tr in soup.select("table.status-details-table tr"):
                    key_cell = tr.find("td", class_="status-details-table__key")
                    if key_cell and key_cell.get_text(strip=True) == "Original URL":
                        val_cell = tr.find("td", class_="status-details-table__value")
                        a = val_cell.find("a", href=True)
                        original_url = a["href"]
                        break

                if not original_url:
                    logger.warning(f"Original URL not found for post: {post.id}")
                    continue

                original_link_mapping[post.id] = original_url
                post.summary = original_url
                post.title = f"See the original post here: {original_url}"
                filtered_posts.append(post)
                summary_exclude.append(post.id)
            else:
                filtered_posts.append(post)

        # 6. Summarize posts as needed
        summary_mapping: dict[str, str] = {}
        for post in filtered_posts:
            if post.id in summary_exclude:
                continue
            summary_mapping[post.id] = await self.summarize_post(post.summary)

        # 7. Build the results
        results: list[dict] = []
        for post in filtered_posts:
            post_dict = post.model_dump()
            post_dict['ai_summary'] = summary_mapping.get(post.id, "No summary available.")
            post_dict['original_link'] = original_link_mapping.get(post.id, post.link)
            results.append(post_dict)

        # 8. Send emails to recipients
        for recipient in self._recipients:
            logger.info(f"Sending email to {recipient}")
            html_content = generate_truth_social_email(results)

            # compute time of day in Eastern
            hour = datetime.now(ZoneInfo("America/New_York")).hour
            time_of_day = 'morning' if hour < 12 else 'afternoon' if hour < 18 else 'evening'

            subject = (
                f"See {len(results)} new Truth Social "
                f"{'posts' if len(results) > 1 else 'post'} for you this {time_of_day}!"
            )
            await self._send_email_sendinblue(recipient, subject, html_content)

        # 9. After successful processing, update cache to newest timestamp
        newest_seen_timestamp = entries[0].published_parsed
        newest_seen_datetime = datetime(*newest_seen_timestamp[:6]).isoformat()
        logger.info(f"Updating cache with latest timestamp: {newest_seen_datetime}")
        await self._cache_client.set_cache(cache_key, newest_seen_datetime, CACHE_TTL_MINUTES)

        return results
