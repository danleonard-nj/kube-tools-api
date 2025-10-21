import html
from typing import Optional

from clients.gpt_client import GPTClient
from domain.google import (DEFAULT_PROMPT_TEMPLATE, GmailEmail,
                           GmailEmailRuleModel, GoogleEmailHeader,
                           clean_unicode, parse_gmail_body_text)
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from framework.validators import none_or_whitespace
from domain.gpt import GPTModel
from framework.clients.feature_client import FeatureClientAsync

logger = get_logger(__name__)

GPT_MODEL_FEATURE_FLAG = 'gpt-model-gmail-rule-engine'


class MessageFormatter:
    """Handles formatting of email messages for SMS notifications."""

    def __init__(
        self,
        gpt_client: GPTClient,
        feature_client: FeatureClientAsync
    ):
        ArgumentNullException.if_none(gpt_client, 'gpt_client')
        ArgumentNullException.if_none(feature_client, 'feature_client')

        self._gpt_client = gpt_client
        self._feature_client = feature_client

    async def _get_configured_gpt_model(self) -> str:
        """Retrieve the configured GPT model from feature flags."""
        return await self._feature_client.is_enabled(
            feature_key=GPT_MODEL_FEATURE_FLAG)

    async def generate_sms_message(
        self,
        rule: GmailEmailRuleModel,
        message: GmailEmail
    ) -> str:
        """Format email message for SMS notification."""
        ArgumentNullException.if_none(rule, 'rule')
        ArgumentNullException.if_none(message, 'message')

        # Check if ChatGPT summary is requested
        chat_gpt_summary = rule.data.chat_gpt_include_summary

        if not chat_gpt_summary:
            return self._build_basic_message(rule, message)

        # Get ChatGPT summary
        prompt_template = rule.data.chat_gpt_prompt_template
        summary = await self._get_chat_gpt_summary(message, prompt_template)

        return self._build_message_with_summary(rule, message, summary)

    def format_balance_sync_message(
        self,
        rule: GmailEmailRuleModel,
        message: GmailEmail
    ) -> str:
        """Format email message for balance sync notifications."""
        ArgumentNullException.if_none(rule, 'rule')
        ArgumentNullException.if_none(message, 'message')

        return self._build_basic_message(rule, message)

    def _build_basic_message(
        self,
        rule: GmailEmailRuleModel,
        message: GmailEmail,
        summary: Optional[str] = None
    ) -> str:
        """Build the SMS message text."""
        ArgumentNullException.if_none(rule, 'rule')
        ArgumentNullException.if_none(message, 'message')

        snippet = clean_unicode(html.unescape(message.snippet)).strip()

        parts = [
            f'Rule: {rule.name}',
            f'Date: {message.timestamp}',
            ''
        ]

        if not none_or_whitespace(snippet):
            parts.extend([snippet, ''])

        if not none_or_whitespace(summary):
            parts.extend([f'GPT: {summary}', ''])

        parts.append(f'From: {message.headers[GoogleEmailHeader.From]}')

        if rule.data.post_forward_email:
            parts.append(f'\nFwd: {rule.data.post_forward_email_to}')

        return '\n'.join(parts)

    def _build_message_with_summary(
        self,
        rule: GmailEmailRuleModel,
        message: GmailEmail,
        summary: str
    ) -> str:
        """Build message with ChatGPT summary."""
        ArgumentNullException.if_none(rule, 'rule')
        ArgumentNullException.if_none(message, 'message')
        ArgumentNullException.if_none(summary, 'summary')

        return self._build_basic_message(rule, message, summary)

    async def _get_chat_gpt_summary(
        self,
        message: GmailEmail,
        prompt_template: Optional[str] = None
    ) -> str:
        """Get email summary using ChatGPT."""
        ArgumentNullException.if_none(message, 'message')

        logger.info('Generating ChatGPT summary for email')

        # Parse email body
        body_segments = parse_gmail_body_text(message=message)
        body_text = ' '.join(body_segments)

        # Build prompt
        prompt = (
            f"{prompt_template}: {body_text}" if not none_or_whitespace(prompt_template)
            else f"{DEFAULT_PROMPT_TEMPLATE}: {body_text}"
        )

        model = await self._get_configured_gpt_model() or GPTModel.GPT_4_1
        logger.info(f'Using GPT model: {model}')

        logger.info('Sending prompt to ChatGPT')
        result = await self._gpt_client.generate_response(
            prompt=prompt,
            model=model
        )

        logger.info(f'ChatGPT email summary usage tokens: {result.usage}')
        return result.text
