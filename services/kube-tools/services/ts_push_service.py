from datetime import datetime

import feedparser
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
    def __init__(
        self,
        cache_client: CacheClientAsync,
        gpt_client: GPTClient,
        email_config: EmailConfig,
        config: TruthSocialConfig
    ):
        self._cache_client = cache_client
        self._gpt_client = gpt_client
        self._feed_url = config.rss_feed

        sib_config = SibConfiguration()
        sib_config.api_key['api-key'] = email_config.sendinblue_api_key.get_secret_value()
        self._sib_client = ApiClient(sib_config)
        self._sib_email_api = TransactionalEmailsApi(self._sib_client)
        self._recipients = config.recipients

    async def _send_email_sendinblue(self, recipient: str, subject: str, html_body: str) -> None:
        """Send email via Sendinblue API."""
        email = SendSmtpEmail(
            to=[{"email": recipient}],
            sender={"email": 'me@dan-leonard.com', "name": "TruthSocial Push Service"},
            subject=subject,
            html_content=html_body
        )

        self._sib_email_api.send_transac_email(email)
        logger.info(f"Email sent successfully to {recipient}")

    async def summarize_post(
        self,
        content: str
    ):
        """
        Summarizes the content of a post using GPT.
        """
        prompt = f"Summarize Donald Trump's post in a neutral, fact-based way, if it needs to be summarized  Try to limit to 3 sentences maximum, shooting for 1 - 2 sentences:\n\n{content}"
        response = await self._gpt_client.generate_completion(
            prompt=prompt,
            model=GPTModel.GPT_4O_MINI,
            max_tokens=250,
            temperature=0.5
        )
        return response.content if response else "No summary available."

    async def get_latest_posts(
        self
    ):
        logger.info("Fetching latest posts from Truth Social feed...")
        cache_key = f"truth_social_latest_post"
        # Getting the latest ID
        latest_id = await self._cache_client.get_cache(cache_key)
        logger.info(f"Latest post ID from cache: {latest_id}")

        # Get the feed (fetch latest 10 posts)
        feed = feedparser.parse(self._feed_url)
        entries = feed.entries[:5]
        logger.info(f"Fetched {len(entries)} entries from the feed.")

        new_posts: list[FeedEntry] = []
        new_latest_id = None

        entries = [FeedEntry.model_validate(entry) for entry in entries]

        for entry in entries:
            if not latest_id or entry.id != latest_id:
                logger.info(f"Processing new post: {entry.id}")
                new_posts.append(entry)
            else:
                break  # Stop at the last seen post

        if not new_posts:
            logger.info("No new posts found since the last check.")
            return []

        if entries:
            new_latest_id = entries[0].id
            logger.info(f"Setting latest post ID: {new_latest_id}")
            await self._cache_client.set_cache(cache_key, new_latest_id)

        summaries = {}
        for post in new_posts:
            content = post.summary
            logger.info(f"Summarizing post: {post.id}")
            summary = await self.summarize_post(content)
            summaries[post.id] = summary

        results = []

        for post in new_posts:
            post_dict = post.model_dump()
            post_dict['ai_summary'] = summaries.get(post.id, "No summary available.")
            results.append(post_dict)

        for recipient in self._recipients:
            logger.info(f"Sending email to {recipient}")
            html_content = generate_truth_social_email(results)

            time_of_day = 'morning'
            if datetime.now().hour >= 12:
                time_of_day = 'afternoon'
            if datetime.now().hour >= 18:
                time_of_day = 'evening'

            post_literal = 'posts' if len(results) > 1 else 'post'

            subject = f"See {len(results)} new Truth Social {post_literal} for you this {time_of_day}!"
            await self._send_email_sendinblue(recipient, subject, html_content)

        return results
