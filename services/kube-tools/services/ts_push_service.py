from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
import feedparser
import httpx
import time

from clients.gpt_client import GPTClient
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


class TruthSocialPushService:
    MAX_TO_PROCESS = 5
    CACHE_KEY = "truth_social_latest_ids"   # now stores a list via get_json/set_json
    CACHE_SIZE = 20                          # keep the last 20 seen IDs
    SENDER_EMAIL = "me@dan-leonard.com"
    SENDER_NAME = "TruthSocial Push Service"
    SUMMARY_MAX_TOKENS = 250
    SUMMARY_TEMPERATURE = 0.5

    def __init__(
        self,
        cache_client: CacheClientAsync,
        gpt_client: GPTClient,
        email_config: EmailConfig,
        config: TruthSocialConfig,
        http_client: httpx.AsyncClient
    ):
        self._cache = cache_client
        self._gpt = gpt_client
        self._feed_url = config.rss_feed
        self._http = http_client
        self._recipients = config.recipients

        sib_cfg = SibConfiguration()
        sib_cfg.api_key['api-key'] = email_config.sendinblue_api_key.get_secret_value()
        api_client = ApiClient(sib_cfg)
        self._email_api = TransactionalEmailsApi(api_client)

    async def get_latest_posts(self) -> list[dict]:
        # 1) Fetch feed entries oldest→newest
        entries = self._fetch_and_sort_feed_ascending()

        # 2) Load our last CACHE_SIZE IDs
        cached_ids = await self._get_latest_cached_ids()

        # 3) Filter out anything already seen
        new_entries = [e for e in entries if e.id not in cached_ids]
        if not new_entries:
            logger.info("No new posts since last check.")
            return []

        # 4) Only process up to MAX_TO_PROCESS of the newest new entries
        to_process = new_entries[-self.MAX_TO_PROCESS:]
        logger.info(f"Processing {len(to_process)} new entries.")

        # 5) Summarize & email
        results = await self._process_posts(to_process)
        await self._dispatch_emails(results)

        # 6) Slide our cache window forward
        latest_ids = [e.id for e in entries][-self.CACHE_SIZE:]
        await self._update_cache_ids(latest_ids)

        return results

    def _fetch_and_sort_feed_ascending(self) -> list[FeedEntry]:
        try:
            raw = feedparser.parse(self._feed_url)

            def entry_timestamp(e):
                """
                Convert published_parsed or updated_parsed to a timestamp,
                or use current time as a fallback.
                """
                parsed = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
                return time.mktime(parsed) if parsed else time.time()

            # Sort oldest→newest by timestamp
            raw.entries.sort(key=entry_timestamp)
            return [FeedEntry.model_validate(e) for e in raw.entries]
        except Exception as err:
            logger.error(f"Error parsing or sorting feed: {err}", exc_info=True)
            raise

    async def _get_latest_cached_ids(self) -> list[str]:
        try:
            return await self._cache.get_json(self.CACHE_KEY) or []
        except Exception as e:
            logger.error(f"Error reading cache IDs: {e}")
            return []

    async def _update_cache_ids(self, ids: list[str]) -> None:
        try:
            await self._cache.set_json(self.CACHE_KEY, ids)
            logger.info(f"Cache updated with {len(ids)} recent IDs")
        except Exception as e:
            logger.error(f"Error updating cache IDs: {e}")

    async def _process_posts(self, posts: list[FeedEntry]) -> list[dict]:
        results = []
        for post in posts:
            original_url = None
            should_summarize = True

            if "No Title" in post.title or post.summary == "<p></p>":
                try:
                    logger.info(f"Fetching original URL for post {post.id}")
                    original_url = await self._fetch_original_url(post.link)
                    if original_url:
                        post.title = f"See the original post here: {original_url}"
                        post.summary = original_url
                        should_summarize = False
                    else:
                        logger.warning(f"Could not find original URL for {post.id}")
                        continue
                except Exception as e:
                    logger.error(f"Error processing post {post.id}: {e}")
                    continue

            ai_summary = "No summary available."
            if should_summarize:
                try:
                    ai_summary = await self.summarize_post(post.summary)
                except Exception as e:
                    logger.error(f"Error summarizing post {post.id}: {e}")
                    ai_summary = "Summary unavailable."

            data = post.model_dump()
            data["original_link"] = original_url or post.link
            data["ai_summary"] = ai_summary
            results.append(data)

        return results

    async def _fetch_original_url(self, link: str) -> str | None:
        try:
            resp = await self._http.get(link)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for tr in soup.select("table.status-details-table tr"):
                key = tr.find("td", class_="status-details-table__key")
                if key and key.get_text(strip=True) == "Original URL":
                    val = tr.find("td", class_="status-details-table__value")
                    if val:
                        a = val.find("a", href=True)
                        if a:
                            return a["href"]
            return None
        except Exception as e:
            logger.error(f"Error fetching original URL from {link}: {e}")
            return None

    async def _dispatch_emails(self, results: list[dict]) -> None:
        if not results:
            return
        html = generate_truth_social_email(results)
        subject = self._generate_subject(len(results))
        for recipient in self._recipients:
            try:
                logger.info(f"Sending email to {recipient}")
                await self._send_email(recipient, subject, html)
            except Exception as e:
                logger.error(f"Failed to send email to {recipient}: {e}")

    async def _send_email(self, to: str, subject: str, html: str) -> None:
        try:
            msg = SendSmtpEmail(
                to=[{"email": to}],
                sender={"email": self.SENDER_EMAIL, "name": self.SENDER_NAME},
                subject=subject,
                html_content=html
            )
            self._email_api.send_transac_email(msg)
            logger.info(f"Email sent successfully to {to}")
        except Exception as e:
            logger.error(f"Email API error for {to}: {e}")
            raise

    def _generate_subject(self, post_count: int) -> str:
        time_of_day = self._get_time_of_day()
        post_word = 'posts' if post_count > 1 else 'post'
        return f"See {post_count} new Truth Social {post_word} for you this {time_of_day}!"

    def _get_time_of_day(self) -> str:
        hour = datetime.now(ZoneInfo("America/New_York")).hour
        if hour < 12:
            return "morning"
        if hour < 18:
            return "afternoon"
        return "evening"

    async def summarize_post(self, content: str) -> str:
        try:
            prompt = (
                f"Summarize Donald Trump's post in a neutral, fact-based way, "
                f"if it needs to be summarized. Try to limit to 3 sentences maximum, "
                f"shooting for 1-2 sentences:\n\n{content}"
            )
            response = await self._gpt.generate_completion(
                prompt=prompt,
                model=GPTModel.GPT_4O_MINI,
                max_tokens=self.SUMMARY_MAX_TOKENS,
                temperature=self.SUMMARY_TEMPERATURE
            )
            return response.content if response else "No summary available."
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return "Summary generation failed."
