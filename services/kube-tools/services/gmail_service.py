import asyncio
import json
import re
from typing import Dict, List

from bs4 import BeautifulSoup
from cachetools import cached
from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from framework.logger import get_logger
from framework.crypto.hashing import sha256
from framework.validators.nulls import none_or_whitespace

from clients.chat_gpt_service_client import (ChatGptException,
                                             ChatGptServiceClient)
from clients.gmail_client import GmailClient
from clients.twilio_gateway import TwilioGatewayClient
from constants.google import (GmailRuleAction, GoogleEmailHeader,
                              GoogleEmailLabel)
from domain.google import GmailEmail, GmailEmailRule, parse_gmail_body
from services.bank_service import BankService
from services.gmail_rule_service import GmailRuleService
from utilities.utils import KeyUtils

logger = get_logger(__name__)


def log_truncate(segment):
    if len(segment) < 100:
        return segment

    return f'{segment[:50]}...{segment[-50:]}'


WELLS_FARGO_RULE_ID = '7062d7af-c920-4f2e-bdc5-e52314d69194'
WELLS_FARGO_BALANCE_EMAIL_KEY = 'Balance summary'
WELLS_FARGO_BANK_KEY = 'wells-fargo'

BankRuleMapping = {
    'e5bec174-12ad-40f1-9413-f8a1e69f2eed': 'chase',
    '7062d7af-c920-4f2e-bdc5-e52314d69194': 'wells-fargo',
    'bffcec15-f23f-4935-9e5e-50282c264325': 'capital-one'
}


class GmailService:
    def __init__(
        self,
        configuration: Configuration,
        gmail_client: GmailClient,
        rule_service: GmailRuleService,
        bank_service: BankService,
        twilio_gateway: TwilioGatewayClient,
        chat_gpt_service_client: ChatGptServiceClient,
        cache_client: CacheClientAsync
    ):
        self.__gmail_client = gmail_client
        self.__rule_service = rule_service
        self.__twilio_gateway = twilio_gateway
        self.__bank_service = bank_service
        self.__chat_gpt_client = chat_gpt_service_client
        self.__cache_client = cache_client

        self.__sms_recipient = configuration.gmail.get(
            'sms_recipient')

    async def run_mail_service(
        self
    ) -> Dict[str, int]:

        logger.info(f'Gathering rules for Gmail rule service')

        run_results = dict()

        rules = await self.__rule_service.get_rules()
        rules.reverse()

        logger.info(f'Rules gathered: {len(rules)}')

        for rule in rules:
            logger.info(f'Processing rule: {rule.rule_id}: {rule.name}')

            # Default affected count
            affected_count = 0

            # Process an archival rule
            if rule.action == GmailRuleAction.Archive:
                logger.info(f'Rule type: {GmailRuleAction.Archive}')

                affected_count = await self.process_archive_rule(
                    rule=rule)

            # Process an SMS rule
            if rule.action == GmailRuleAction.SMS:
                logger.info(f'Rule type: {GmailRuleAction.SMS}')

                affected_count = await self.process_sms_rule(
                    rule=rule)

            run_results[rule.name] = affected_count
            logger.info(
                f'Rule: {rule.name}: Emails affected: {affected_count}')

        asyncio.create_task(self.__rule_service.log_results(
            results=run_results))

        return run_results

    async def process_archive_rule(
        self,
        rule: GmailEmailRule
    ) -> List[str]:

        # Query the inbox w/ the defined rule query
        query_result = await self.__gmail_client.search_inbox(
            query=rule.query,
            max_results=rule.max_results)

        logger.info(f'Result count: {len(query_result.messages or [])}')

        archived = 0
        for message_id in query_result.message_ids or []:
            message = await self.__gmail_client.get_message(
                message_id=message_id)

            if GoogleEmailLabel.Inbox not in message.label_ids:
                continue

            logger.info(f'Rule: {rule.name}: Archiving email: {message_id}')

            archived += 1
            await self.__gmail_client.archive_message(
                message_id=message_id)

        return archived

    async def process_sms_rule(
        self,
        rule: GmailEmailRule
    ):
        logger.info(f'Processing SMS rule: {rule.name}')

        # Query the inbox w/ the defined rule query
        query_result = await self.__gmail_client.search_inbox(
            query=rule.query,
            max_results=rule.max_results)

        logger.info(f'Query result count: {len(query_result.messages)}')
        notify_count = 0

        for message_id in query_result.message_ids:
            logger.debug(f'Get email message: {message_id}')

            message = await self.__gmail_client.get_message(
                message_id=message_id)

            # If the email is read, ignore it
            if GoogleEmailLabel.Unread not in message.label_ids:
                continue

            logger.info(f'Message eligible for notification: {message_id}')

            body = await self.__get_message_body(
                rule=rule,
                message=message)

            logger.info(f'Message body: {body}')

            # Send the email snippet in the message body
            await self.__twilio_gateway.send_sms(
                recipient=self.__sms_recipient,
                message=body)

            # Mark read the email so another notification isn't sent
            to_add = [GoogleEmailLabel.Starred]

            to_remove = [GoogleEmailLabel.Unread,
                         GoogleEmailLabel.Inbox]

            await self.__gmail_client.modify_tags(
                message_id=message_id,
                to_add=to_add,
                to_remove=to_remove)

            logger.info(f'Tags add/remove: {to_add}: {to_remove}')

            notify_count += 1

        return notify_count

    async def __get_message_body(
        self,
        rule: GmailEmailRule,
        message: GmailEmail
    ):
        body = f'From: {message.headers[GoogleEmailHeader.From]}'
        body = f'Rule: {rule.name} ({rule.rule_id})'
        body += '\n'
        body += f'Date: {message.timestamp}'
        body += '\n'
        body += '\n'
        body += message.snippet
        body += '\n'
        body += '\n'
        body += f'https://mail.google.com/mail/u/0/#inbox/{message.message_id}'

        if rule.rule_id in BankRuleMapping:
            logger.info('Bank rule detected')

            await self.handle_bank_email(
                rule_id=rule.rule_id,
                message=message)

        return body

    def clean_message_string(
        self,
        message: str
    ):
        logger.info(f'Initial message length: {len(message)}')

        # Remove unwanted chars
        message = ''.join([
            c for c in message
            if c.isalnum()
            or c in ['.', '$', ' ']
        ])

        # Consolidate spaces
        message = re.sub(' +', ' ', message)

        logger.info(f'Reduced message length: {len(message)}')

        return message

    def get_chat_gpt_balance_prompt(
        self,
        message: str
    ):
        prefix = 'Get the current available bank balance (if present) from this string'
        suffix = 'Response with only the balance or "N/A"'
        prompt = f"{prefix}: '{message}'. {suffix}"

        logger.info(f'Prompt: {prompt}')
        return prompt

    def get_email_body_text(
        self,
        segments: List[str]
    ) -> List[str]:
        logger.info(f'Parsing email body segments: {len(segments)}')

        results = []
        for segment in segments:
            if none_or_whitespace(segment):
                logger.info(f'Segment is empty')
                continue

            logger.info(f'Parsing segment: {log_truncate(segment)}')
            soup = BeautifulSoup(segment)

            body = soup.find('body')

            if body is None:
                logger.info(f'No body found in segment')
                continue

            content = (
                body
                .get_text()
                .strip()
                .replace('\n', ' ')
                .replace('\t', '')
                .replace('\r', '')
            )

            results.append(content)

        return results

    def is_banking_email(
        self,
        segment: str,
        match_threshold=3
    ):
        matches = []
        keys = [
            'balance',
            'bank',
            'wells',
            'fargo',
            'chase',
            'discover',
            'account',
            'summary'
            'activity',
            'transactions',
            'credit',
            'card'
        ]

        text = segment.lower()

        for key in keys:
            if key in text:
                logger.info(f'Bank email key matched: {key}')
                matches.append(key)

        return len(matches) >= match_threshold

    async def handle_bank_email(
        self,
        rule_id: str,
        message: GmailEmail
    ):

        try:
            logger.info(f'Parsing Gmail body')
            email_body_segments = parse_gmail_body(
                message=message)

            if none_or_whitespace(email_body_segments):
                email_body_segments = [message.snippet]
                logger.info(f'Using snippet instead of email body')

            else:
                logger.info(f'Parsing email body')
                email_body_segments = self.get_email_body_text(
                    segments=email_body_segments)

            balance = 'UNDEFINED'
            total_tokens = 0
            for segment in email_body_segments:
                # If the email text does not contain more than the
                # threshold number of banking keywords it doesn't
                # meet the criteria for a banking email
                if not self.is_banking_email(
                        segment=segment,
                        match_threshold=3):
                    continue

                # Reduce message length
                logger.info(f'Cleaning message string')
                segment = self.clean_message_string(
                    message=segment)

                if len(segment) > 500:
                    logger.info(
                        f'Truncating segment from {len(segment)} to 500 chars')
                    segment = segment[:500]

                logger.info(f'Generating balance prompt')
                balance_prompt = self.get_chat_gpt_balance_prompt(
                    message=segment)

                logger.info(f'Balance prompt: {log_truncate(balance_prompt)}')

                key = f'gpt-balance-prompt-{sha256(balance_prompt)}'
                cached_response = await self.__cache_client.get_json(
                    key=key)

                if cached_response is not None:
                    balance = cached_response.get('balance')
                    usage = cached_response.get('usage')

                else:

                    # Max 5 attempts to parse balance from string
                    for _ in range(5):
                        try:
                            logger.info(f'Parse balance from string w/ GPT')
                            balance, usage = await self.__chat_gpt_client.get_chat_completion(
                                prompt=balance_prompt)

                            # Fire the cache task
                            self.fire_cache_gpt_response(
                                key=key,
                                balance=balance,
                                usage=usage)

                            logger.info(f'Breaking from GPT loop')
                            break

                        except ChatGptException as ex:
                            if ex.retry:
                                logger.info(
                                    f'GPT retryable error: {ex.message}')
                            else:
                                logger.info(
                                    f'GPT non-retryable error: {ex.message}')
                                balance = 'N/A'
                                break

                if usage > 0:
                    total_tokens += usage

                if balance != 'N/A':
                    break
                else:
                    logger.info(
                        f'GPT failed to find balance info in string: {log_truncate(balance_prompt)}')

            # Strip currency formatting chars
            num_results = re.findall("\d+\.\d+", balance)

            if any(num_results):
                balance = num_results[0]

            balance = balance.replace('$', '').replace(',', '')

            if balance == 'UNDEFINED':
                logger.info(f'Balance not found in email')
                return

            # Strip any formatting chars
            balance = float(balance)

            logger.info(f'Balance: {balance}')

            bank_key = BankRuleMapping.get(rule_id)

            logger.info(f'Bank key: {bank_key}')

            # For CapitalOne emails, we need to determine the card type
            # to store the balance against
            if bank_key == 'capital-one':
                logger.info(f'Parsing CapitalOne card type')
                bank_key = self.get_capital_one_bank_key(
                    body_segments=email_body_segments)

            await self.__bank_service.capture_balance(
                bank_key=bank_key,
                balance=float(balance),
                tokens=total_tokens)

        except Exception as ex:
            logger.exception(f'Error parsing balance: {ex.message}')
            balance = 0.0

    def get_capital_one_bank_key(
        self,
        body_segments: List[str]
    ):
        bank_key = 'capital-one'

        for email_body in body_segments:
            email_body = email_body.lower()

            if 'savorone' in email_body:
                logger.info(f'CapitalOne SavorOne card detected')
                bank_key = f'{bank_key}-savorone'
                break
            if 'venture' in email_body:
                logger.info(f'CapitalOne Venture card detected')
                bank_key = f'{bank_key}-venture'
                break
            if 'quicksilver' in email_body:
                logger.info(f'CapitalOne Quiksilver card detected')
                bank_key = f'{bank_key}-quiksilver'
                break

        return bank_key

    def fire_cache_gpt_response(
        self,
        key: str,
        balance: float,
        usage: int
    ):
        logger.info(f'Firing cache task for GPT response')

        value = dict(
            balance=balance,
            usage=usage
        )

        asyncio.create_task(
            self.__cache_client.set_json(
                key=key,
                value=value,
                ttl=60 * 60 * 24 * 7))
