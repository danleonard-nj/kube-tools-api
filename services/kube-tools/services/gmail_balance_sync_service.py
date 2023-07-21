import asyncio
import re
from typing import Dict, List

from bs4 import BeautifulSoup
from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from framework.crypto.hashing import sha256
from framework.logger import get_logger
from framework.validators.nulls import none_or_whitespace

from clients.chat_gpt_service_client import (ChatGptException,
                                             ChatGptServiceClient)
from domain.bank import BankRuleConfig, SyncType
from domain.cache import CacheKey
from domain.google import GmailEmail, GmailEmailRule, parse_gmail_body
from services.bank_service import BankKey, BankService
from services.gmail_rule_service import GmailRuleService

logger = get_logger(__name__)


WELLS_FARGO_RULE_ID = '7062d7af-c920-4f2e-bdc5-e52314d69194'
WELLS_FARGO_BALANCE_EMAIL_KEY = 'Balance summary'
WELLS_FARGO_BANK_KEY = 'wells-fargo'

PROMPT_PREFIX = 'Get the current available bank balance (if present) from this string'
PROMPT_SUFFIX = 'Respond with only the balance or "N/A"'


CAPITAL_ONE_SAVOR = 'savor'
CAPITAL_ONE_QUICKSILVER = 'quicksilver'
CAPITAL_ONE_VENTURE = 'venture'

SYNCHRONY_AMAZON = 'prime store card'
SYNCHRONY_GUITAR_CENTER = 'guitar center'
SYNCHRONY_SWEETWATER = 'sweetwater sound'

BALANCE_EMAIL_INCLUSION_KEYWORDS = [
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


def log_truncate(segment):
    if len(segment) < 100:
        return segment

    return f'{segment[:50]}...{segment[-50:]}'


class GmailBankSyncService:
    def __init__(
        self,
        configuration: Configuration,
        rule_service: GmailRuleService,
        bank_service: BankService,
        chat_gpt_service_client: ChatGptServiceClient,
        cache_client: CacheClientAsync,
    ):
        self.__rule_service = rule_service
        self.__bank_service = bank_service
        self.__chat_gpt_client = chat_gpt_service_client
        self.__cache_client = cache_client

        self.__bank_rules = configuration.banking.get(
            'rules')

        self.__bank_rule_mapping: Dict[str, BankRuleConfig] = None

    async def handle_balance_sync(
        self,
        rule: GmailEmailRule,
        message: GmailEmail
    ):
        # Lazy load the bank rule mapping
        if self.__bank_rule_mapping is None:
            logger.info(f'Fetching bank rule mapping')
            self.__bank_rule_mapping = await self.__generate_bank_rule_mapping()

        if rule.rule_id in self.__bank_rule_mapping:
            logger.info('Bank rule detected')

        try:
            logger.info(f'Parsing Gmail body')
            email_body_segments = parse_gmail_body(
                message=message)

            # If we can't parse the body then use the snippet
            if none_or_whitespace(email_body_segments):
                email_body_segments = [message.snippet]
                logger.info(f'Using snippet instead of email body')

            else:
                logger.info(f'Parsing email body')
                email_body_segments = self.__get_email_body_text(
                    segments=email_body_segments)

            balance = 'UNDEFINED'
            total_tokens = 0
            for segment in email_body_segments:
                # If the email text does not contain more than the
                # threshold number of banking keywords it doesn't
                # meet the criteria for a banking email
                if not self.__is_banking_email(
                        segment=segment,
                        match_threshold=3):
                    continue

                # Reduce message length
                logger.info(f'Cleaning message string')
                segment = self.__clean_message_string(
                    message=segment)

                # Truncate the reduced message to 500 chars max not
                # to exceed GPTs token limit
                if len(segment) > 500:
                    logger.info(
                        f'Truncating segment from {len(segment)} to 500 chars')
                    segment = segment[:500]

                logger.info(f'Generating balance prompt')
                # Generate the GPT prompt to get the balance from
                # the string
                balance_prompt = self.__get_chat_gpt_balance_prompt(
                    message=segment)

                logger.info(f'Balance prompt: {log_truncate(balance_prompt)}')

                key = f'gpt-balance-prompt-{sha256(balance_prompt)}'
                cached_response = await self.__cache_client.get_json(
                    key=key)

                if cached_response is not None:
                    logger.info(f'Using cached GPT: {cached_response}')
                    balance = cached_response.get('balance')
                    usage = cached_response.get('usage')

                else:

                    # Max 5 attempts to parse balance from string
                    for attempt in range(5):
                        try:
                            logger.info(
                                f'Parse balance from string w/ GPT: Attempt {attempt + 1}')

                            # Submit the prompt to GPT and get the response
                            # and tokens used
                            balance, usage = await self.__chat_gpt_client.get_chat_completion(
                                prompt=balance_prompt)

                            logger.info(
                                f'GPT response balance / usage: {balance} : {usage}')

                            # Fire the cache task
                            self.__fire_cache_gpt_response(
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

                # Capture the total tokens used
                if usage > 0:
                    total_tokens += usage

                # If we've got the balance from this email segment
                # then break out the jobs done
                if balance != 'N/A':
                    break
                else:
                    logger.info(
                        f'Failed to find balance info in string: {log_truncate(balance_prompt)}')

            if balance in ['UNDEFINED', 'N/A']:
                logger.info(f'Balance not found in email: {balance}')
                return

            # Strip duplicate spaces w/ regex
            num_results = re.findall("\d+\.\d+", balance)
            logger.info(f'Regexed balance result: {num_results}')

            # Update the balance to the regex result if found
            if any(num_results):
                balance = num_results[0]

            # Strip any currency formatting chars
            balance = balance.replace('$', '').replace(',', '')
            logger.info(f'Balance stripped currency formatting: {balance}')

            # If we still don't have a balance then bail out
            if balance in ['UNDEFINED', 'N/A']:
                logger.info(f'Balance not found in email')
                return

            # Try to parse the balance as a float
            try:
                balance = float(balance)
                logger.info(f'Balance successfully parsed as float: {balance}')
            except Exception as ex:
                logger.info(f'Balance is not a float: {balance}')
                raise Exception(f'Failed to parse balance: {balance}') from ex

            logger.info(f'Balance: {balance}')

            # Get the bank rule config from the rule mapping
            mapped_rule = self.__bank_rule_mapping.get(rule.rule_id)
            logger.info(f'Mapped bank rule config: {mapped_rule.to_dict()}')

            if mapped_rule is None:
                raise Exception(
                    f"No bank rule mapping found for rule ID '{rule.rule_id}'")

            bank_key = mapped_rule.bank_key
            logger.info(f'Bank key: {bank_key}')

            # For CapitalOne emails, we need to determine the card type
            # to store the balance against
            if bank_key == 'capital-one':
                logger.info(f'Parsing CapitalOne card type')
                bank_key = self.__get_capital_one_bank_key(
                    body_segments=email_body_segments)

                # If the bank key is unchanged then we were unable to
                # determine the card type
                if bank_key == BankKey.CapitalOne:
                    logger.info(f'No CapitalOne card type detected')
                    return

            # Same case for Synchrony bank email alerts
            if bank_key == BankKey.Synchrony:
                logger.info(f'Parsing Synchrony card type')
                bank_key = self.__get_synchrony_bank_key(
                    body_segments=email_body_segments)

                # If the bank key is unchanged then we were unable to
                # determine the card type
                if bank_key == BankKey.Synchrony:
                    logger.info(f'No Synchrony card type detected')
                    return

            # Store the balance record
            await self.__bank_service.capture_balance(
                bank_key=bank_key,
                balance=float(balance),
                tokens=total_tokens,
                message_bk=message.message_id,
                sync_type=SyncType.Email)

            logger.info(f'Balance captured successfully for bank: {bank_key}')

        except Exception as ex:
            logger.exception(f'Error parsing balance: {ex.message}')
            balance = 0.0

    async def __generate_bank_rule_mapping(
        self
    ):
        logger.info(f'Generating bank rule mapping')
        cache_key = CacheKey.bank_rule_mapping()

        logger.info(f'Mapping cache key: {cache_key}')
        mapping = await self.__cache_client.get_json(
            key=cache_key)

        if mapping is not None:
            logger.info(f'Cache hit: {cache_key}')
            for key, value in mapping.items():
                logger.info(
                    f'Parsing cached bank rule mapping: {key}: {value}')
                mapping[key] = BankRuleConfig.from_json_object(value)

            return mapping

        rules = self.__bank_rules
        logger.info(f'Banking rule configs: {rules}')

        # Parse the rule configurations
        rule_configs = [BankRuleConfig.from_json_object(data=rule)
                        for rule in rules]

        logger.info(f'Rule configs: {rule_configs}')

        # Names of all the configured rules
        rule_names = [x.rule_name
                      for x in rule_configs]

        logger.info(f'Rule names: {rule_names}')

        # Fetch given rules by rule name
        rules = await self.__rule_service.get_rules_by_name(
            rules=rule_names)

        # Mapping to get the rule config from the name
        rule_lookup = {
            x.name: x for x in rules
        }

        mapping = dict()
        cache_values = dict()

        # Generate the rule ID to rule config mapping
        for rule_config in rule_configs:
            logger.info(
                f'Rule: {rule_config.rule_name}: {rule_config.bank_key}')

            mapped_rule = rule_lookup.get(rule_config.rule_name)

            # Map the rule ID to the rule config which contains
            # the bank key and the rule name
            mapping[mapped_rule.rule_id] = rule_config

            # Set the cache value for this rule config (serialize
            # the bank rule config)
            cache_values[mapped_rule.rule_id] = rule_config.to_dict()

        logger.info(f'Caching rule mapping: {cache_key}: {cache_values}')
        asyncio.create_task(
            self.__cache_client.set_json(
                key=cache_key,
                value=cache_values,
                ttl=5))

        return mapping

    def __get_email_body_text(
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

            # Parse the segment as HTML
            soup = BeautifulSoup(segment)

            # Get the body of the email
            body = soup.find('body')

            # If there is no body in this HTML segment
            # then skip it and move on to the next one
            if body is None:
                logger.info(f'No body found in segment')
                continue

            # Get the text content of the body and strip
            # any newlines, tabs, or carriage returns
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

    def __get_chat_gpt_balance_prompt(
        self,
        message: str
    ) -> str:

        # Generate the prompt to get the balance from the email string
        prompt = f"{PROMPT_PREFIX}: '{message}'. {PROMPT_SUFFIX}"

        logger.info(f'Prompt: {prompt}')

        return prompt

    def __is_banking_email(
        self,
        segment: str,
        match_threshold=3
    ) -> bool:

        matches = []

        text = segment.lower()

        # If the email contains the balance email key
        # add it to the match list
        for key in BALANCE_EMAIL_INCLUSION_KEYWORDS:
            if key in text:
                matches.append(key)

        is_match = (
            len(matches) >= match_threshold
            and 'balance' in matches
        )

        return is_match

    def __clean_message_string(
        self,
        message: str
    ) -> str:

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

    def __get_synchrony_bank_key(
        self,
        body_segments: List[str]
    ):
        logger.info('Parsing Synchrony card type')

        bank_key = BankKey.Synchrony

        for email_body in body_segments:
            email_body = email_body.lower()

            if SYNCHRONY_AMAZON in email_body:
                logger.info(f'Synchrony Amazon card detected')
                bank_key = BankKey.SynchronyAmazon
                break

            if SYNCHRONY_GUITAR_CENTER in email_body:
                logger.info(f'Synchrony Guitar Center card detected')
                bank_key = BankKey.SynchronyGuitarCenter
                break

            if SYNCHRONY_SWEETWATER in email_body:
                logger.info(f'Synchrony Sweetwater card detected')
                bank_key = BankKey.SynchronySweetwater
                break

        return bank_key

    def __get_capital_one_bank_key(
        self,
        body_segments: List[str]
    ):
        logger.info(f'Parsing CapitalOne card type')

        bank_key = BankKey.CapitalOne

        for email_body in body_segments:
            email_body = email_body.lower()

            # SavorOne
            if CAPITAL_ONE_SAVOR in email_body:
                logger.info(f'CapitalOne SavorOne card detected')
                bank_key = BankKey.CapitalOneSavor
                break
            # VentureOne
            if CAPITAL_ONE_VENTURE in email_body:
                logger.info(f'CapitalOne Venture card detected')
                bank_key = BankKey.CapitalOneVenture
                break
            # QuickSilver
            if CAPITAL_ONE_QUICKSILVER in email_body:
                logger.info(f'CapitalOne Quicksilver card detected')
                bank_key = BankKey.CapitalOneQuickSilver
                break

        logger.info(f'CapitalOne bank key: {bank_key}')

        return bank_key

    def __fire_cache_gpt_response(
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
                ttl=60 * 24))
