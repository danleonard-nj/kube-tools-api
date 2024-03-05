import asyncio
import re
from typing import Dict, List

from bs4 import BeautifulSoup
from clients.chat_gpt_service_client import (ChatGptException,
                                             ChatGptServiceClient)
from domain.bank import (BALANCE_EMAIL_EXCLUSION_KEYWORDS,
                         BALANCE_EMAIL_INCLUSION_KEYWORDS,
                         CAPITAL_ONE_QUICKSILVER, CAPITAL_ONE_SAVOR,
                         CAPITAL_ONE_VENTURE, DEFAULT_BALANCE, PROMPT_PREFIX,
                         PROMPT_SUFFIX, SYNCHRONY_AMAZON,
                         SYNCHRONY_GUITAR_CENTER, SYNCHRONY_SWEETWATER,
                         BankRuleConfiguration, ChatGptBalanceCompletion,
                         strip_special_chars)
from domain.cache import CacheKey
from domain.enums import BankKey, SyncType
from domain.google import GmailEmail, GmailEmailRule, parse_gmail_body
from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from framework.logger import get_logger
from framework.validators.nulls import none_or_whitespace
from services.bank_service import BankService
from services.gmail_rule_service import GmailRuleService

logger = get_logger(__name__)


class BankRuleMappingNotFoundException(Exception):
    pass


class GmailBankSyncService:
    def __init__(
        self,
        configuration: Configuration,
        rule_service: GmailRuleService,
        bank_service: BankService,
        chat_gpt_service_client: ChatGptServiceClient,
        cache_client: CacheClientAsync,
    ):
        self._rule_service = rule_service
        self._bank_service = bank_service
        self._chat_gpt_client = chat_gpt_service_client
        self._cache_client = cache_client

        self._bank_rules = configuration.banking.get(
            'rules')

        self._bank_rule_mapping: Dict[str, BankRuleConfiguration] = None

    async def _lazy_load_bank_rule_mapping(
        self
    ) -> None:
        # Lazy load the bank rule mapping
        if self._bank_rule_mapping is None:
            logger.info(f'Fetching bank rule mapping')
            self._bank_rule_mapping = await self._generate_bank_rule_mapping()

    async def handle_balance_sync(
        self,
        rule: GmailEmailRule,
        message: GmailEmail
    ) -> BankRuleConfiguration:

        await self._lazy_load_bank_rule_mapping()

        if rule.rule_id in self._bank_rule_mapping:
            logger.info('Bank rule detected')

        # Get the bank rule config from the rule mapping
        mapped_rule = self._bank_rule_mapping.get(rule.rule_id)

        if mapped_rule is None:
            raise BankRuleMappingNotFoundException(
                f"No bank rule mapping found for rule ID '{rule.rule_id}'")

        logger.info(f'Mapped bank rule config: {mapped_rule.to_dict()}')

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
                email_body_segments = self._get_email_body_text(
                    segments=email_body_segments)

            balance = DEFAULT_BALANCE
            total_tokens = 0

            # Look at each segment of the email
            # body
            for segment in email_body_segments:

                # If the email text does not contain more than the
                # threshold number of banking keywords it doesn't
                # meet the criteria for a banking email
                if not self._is_banking_email(
                        segment=segment,
                        match_threshold=3):
                    continue

                # Reduce message length
                logger.info(f'Cleaning message string')
                segment = self._clean_message_string(
                    value=segment)

                logger.info(f'Generating balance prompt')
                # Generate the GPT prompt to get the balance from
                # the string
                balance_prompt = self._get_chat_gpt_balance_prompt(
                    message=segment)

                logger.info(f'Balance prompt: {balance_prompt}')

                gpt_result = await self._get_chat_gpt_balance_completion(
                    balance_prompt=balance_prompt)

                if gpt_result.usage > 0:
                    total_tokens += gpt_result.usage

                if (gpt_result.is_success
                        and gpt_result.balance != DEFAULT_BALANCE):
                    balance = gpt_result.balance
                    break

            # Failed to get the balance from any email body
            # segment at this point so bail out
            if balance == DEFAULT_BALANCE:
                logger.info(
                    f'Balance not found in email for rule: {mapped_rule.rule_name}')
                return

            balance = self._format_balance_result(balance)

            # If the balance is N/A then bail out
            if 'N/A' in balance:
                logger.info(f'Balance is N/A')
                return

            # Try to parse the balance as a float
            try:
                balance = float(balance)
                logger.info(f'Balance successfully parsed as float: {balance}')
            except Exception as ex:
                logger.info(f'Balance is not a float: {balance}')
                raise Exception(f'Failed to parse balance: {balance}') from ex

            logger.info(f'Balance: {balance}')

            # Get the bank key from the rule
            bank_key = mapped_rule.bank_key
            logger.info(f'Bank key: {bank_key}')

            # Determine the bank key based on the email body
            bank_key = self._handle_account_specific_balance_sync(
                bank_key=bank_key,
                email_body_segments=email_body_segments)

            # Store the balance record
            await self._bank_service.capture_balance(
                bank_key=bank_key,
                balance=float(balance),
                tokens=total_tokens,
                message_bk=message.message_id,
                sync_type=SyncType.Email)

            logger.info(f'Balance captured successfully for bank: {bank_key}')

        except Exception as ex:
            logger.exception(f'Error parsing balance: {str(ex)}')
            # balance = 0.0

        return mapped_rule

    def _handle_account_specific_balance_sync(
        self,
        bank_key,
        email_body_segments: List[str]
    ):
        match bank_key:
            case BankKey.CapitalOne:
                # For CapitalOne emails, we need to determine the card type
                # to store the balance against
                logger.info(f'Parsing CapitalOne card type')
                return self._get_capital_one_bank_key(
                    body_segments=email_body_segments)

            case BankKey.Synchrony:
                # Same case for Synchrony bank email alerts
                return self._get_synchrony_bank_key(
                    body_segments=email_body_segments)

            case _:
                # Unchanged bank key
                return bank_key

    def _format_balance_result(
        self,
        balance: str
    ):
        # Strip duplicate spaces w/ regex
        num_results = re.findall("\d+\.\d+", balance)
        logger.info(f'Regexed balance result: {num_results}')

        # Update the balance to the regex result if found
        if any(num_results):
            balance = num_results[0]

        # Strip any currency formatting chars
        balance = balance.replace('$', '').replace(',', '')
        logger.info(f'Balance stripped currency formatting: {balance}')

        return balance

    async def _get_chat_gpt_balance_completion(
        self,
        balance_prompt: str
    ) -> ChatGptBalanceCompletion:

        key = CacheKey.chat_gpt_response_by_balance_prompt(
            balance_prompt=balance_prompt)

        cached_response = await self._cache_client.get_json(
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
                    balance, usage = await self._chat_gpt_client.get_chat_completion(
                        prompt=balance_prompt)

                    logger.info(
                        f'GPT response balance / usage: {balance} : {usage}')

                    # Fire the cache task
                    self._fire_cache_gpt_response(
                        key=key,
                        balance=balance,
                        usage=usage)

                    logger.info(f'Breaking from GPT loop')
                    break

                except ChatGptException as ex:
                    # Retryable errors
                    if ex.retry:
                        logger.info(f'GPT retryable error: {ex.message}')
                    # Non-retryable errors
                    else:
                        logger.info(f'GPT non-retryable error: {ex.message}')
                        balance = 'N/A'
                        break

        balance = (balance if balance != 'N/A'
                   else DEFAULT_BALANCE)

        return ChatGptBalanceCompletion.from_balance_response(
            balance=balance,
            usage=usage)

    async def _generate_bank_rule_mapping(
        self
    ):
        logger.info(f'Generating bank rule mapping')
        cache_key = CacheKey.bank_rule_mapping()

        logger.info(f'Mapping cache key: {cache_key}')
        mapping = await self._cache_client.get_json(
            key=cache_key)

        if mapping is not None:
            logger.info(f'Cache hit: {cache_key}')
            for key, value in mapping.items():
                logger.info(
                    f'Parsing cached bank rule mapping: {key}: {value}')
                mapping[key] = BankRuleConfiguration.from_json_object(value)

            return mapping

        rules = self._bank_rules

        # Parse the rule configurations
        rule_configs = [BankRuleConfiguration.from_json_object(data=rule)
                        for rule in rules]

        # Fetch given rules by rule name
        rules = await self._rule_service.get_rules_by_name(
            rule_names=[x.rule_name for x in rule_configs])

        # Mapping to get the rule config from the name
        rule_lookup = {
            x.name: x for x in rules
        }

        mapping = dict()

        # Generate the rule ID to rule config mapping
        for rule_config in rule_configs:
            mapped_rule = rule_lookup.get(rule_config.rule_name)

            # Map the rule ID to the rule config which contains
            # the bank key and the rule name
            mapping[mapped_rule.rule_id] = rule_config

        cache_values = {
            key: value.to_dict()
            for key, value in mapping.items()
        }

        logger.info(f'Caching rule mapping: {cache_key}: {cache_values}')

        asyncio.create_task(
            self._cache_client.set_json(
                key=cache_key,
                value=cache_values,
                ttl=5))

        return mapping

    def _get_email_body_text(
        self,
        segments: List[str]
    ) -> List[str]:
        logger.info(f'Parsing email body segments: {len(segments)}')

        results = []
        for segment in segments:

            if none_or_whitespace(segment):
                logger.info(f'Email body segment is empty: {segment}')
                continue

            # Parse the segment as HTML
            soup = BeautifulSoup(segment)

            # Get the body of the email
            body = soup.find('body')

            # If there is no body in this HTML segment
            # then skip it and move on to the next one
            if none_or_whitespace(body):
                logger.info(f'No text found in body segment: {body}')
                continue

            # Get the text content of the body and strip
            # any newlines, tabs, or carriage returns
            content = strip_special_chars(
                value=body.get_text()
            )

            results.append(content)

        return results

    def _get_chat_gpt_balance_prompt(
        self,
        message: str
    ) -> str:

        # Generate the prompt to get the balance from the email string
        return f"{PROMPT_PREFIX}: '{message}'. {PROMPT_SUFFIX}"

    def _is_banking_email(
        self,
        segment: str,
        match_threshold=3
    ) -> bool:

        matches = []
        text = segment.lower()

        # If the email contains any exclsuion keywords
        for key in BALANCE_EMAIL_EXCLUSION_KEYWORDS:
            if key in text:
                return False

        # If the email contains the balance email key
        # add it to the match list
        for key in BALANCE_EMAIL_INCLUSION_KEYWORDS:
            if key in text:
                matches.append(key)

        return (
            len(matches) >= match_threshold
            and 'balance' in matches
        )

    def _clean_message_string(
        self,
        value: str,
    ) -> str:

        logger.info(f'Initial message length: {len(value)}')

        # Remove unwanted chars
        value = ''.join([
            c for c in value
            if c.isalnum()
            or c in ['.', '$', ' ']
        ])

        # Consolidate spaces
        value = re.sub(' +', ' ', value)

        logger.info(f'Reduced message length: {len(value)}')

        # Truncate the reduced message to 500 chars max not
        # to exceed GPTs token limit
        if len(value) > 500:
            logger.info(
                f'Truncating segment from {len(value)} to 500 chars')
            return value[:500]

        return value

    def _get_synchrony_bank_key(
        self,
        body_segments: List[str]
    ) -> str:

        logger.info('Parsing Synchrony card type')

        bank_key = BankKey.Synchrony

        for email_body in body_segments:
            email_body = email_body.lower()

            # Amazon Prime Store Card
            if SYNCHRONY_AMAZON in email_body:
                logger.info(f'Synchrony Amazon card detected')
                return BankKey.SynchronyAmazon

            # Guitar Center Card
            if SYNCHRONY_GUITAR_CENTER in email_body:
                logger.info(f'Synchrony Guitar Center card detected')
                return BankKey.SynchronyGuitarCenter

            # Sweetwater Card
            if SYNCHRONY_SWEETWATER in email_body:
                logger.info(f'Synchrony Sweetwater card detected')
                return BankKey.SynchronySweetwater

        return bank_key

    def _get_capital_one_bank_key(
        self,
        body_segments: List[str]
    ) -> str:

        logger.info(f'Parsing CapitalOne card type')

        bank_key = BankKey.CapitalOne

        for email_body in body_segments:
            email_body = email_body.lower()

            # SavorOne
            if CAPITAL_ONE_SAVOR in email_body:
                logger.info(f'CapitalOne SavorOne card detected')
                return BankKey.CapitalOneSavor
            # VentureOne
            if CAPITAL_ONE_VENTURE in email_body:
                logger.info(f'CapitalOne Venture card detected')
                return BankKey.CapitalOneVenture
            # QuickSilver
            if CAPITAL_ONE_QUICKSILVER in email_body:
                logger.info(f'CapitalOne Quicksilver card detected')
                return BankKey.CapitalOneQuickSilver

        logger.info(f'CapitalOne bank key: {bank_key}')

        return bank_key

    def _fire_cache_gpt_response(
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
            self._cache_client.set_json(
                key=key,
                value=value,
                ttl=60 * 24))
