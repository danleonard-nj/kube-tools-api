import re
from typing import List
from domain.bank import (BALANCE_EMAIL_EXCLUSION_KEYWORDS,
                         BALANCE_EMAIL_INCLUSION_KEYWORDS,
                         CAPITAL_ONE_QUICKSILVER, CAPITAL_ONE_SAVOR,
                         CAPITAL_ONE_VENTURE, DEFAULT_BALANCE, PROMPT_PREFIX,
                         PROMPT_SUFFIX, SYNCHRONY_AMAZON,
                         SYNCHRONY_GUITAR_CENTER, SYNCHRONY_SWEETWATER,
                         ChatGptBalanceCompletion)
from domain.cache import CacheKey
from domain.enums import BankKey, SyncType
from domain.exceptions import GmailBalanceSyncException
from domain.google import GmailEmail, GmailEmailRule, parse_gmail_body_text
from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from framework.logger import get_logger
from services.bank_service import BankService
from services.chat_gpt_service import ChatGptService
from utilities.utils import fire_task

logger = get_logger(__name__)


class GmailBankSyncService:
    def __init__(
        self,
        configuration: Configuration,
        bank_service: BankService,
        chat_gpt_service: ChatGptService,
        cache_client: CacheClientAsync,
    ):
        self._bank_service = bank_service
        self._chat_gpt_service = chat_gpt_service
        self._cache_client = cache_client

        self._bank_rules = configuration.banking.get(
            'rules')

    async def handle_balance_sync(
        self,
        rule: GmailEmailRule,
        message: GmailEmail,
        bank_key: str
    ):
        try:
            logger.info(f'Parsing Gmail body')

            email_body_segments = parse_gmail_body_text(
                message=message)

            logger.info(f'Email body segments: {len(email_body_segments)}')

            if not any(email_body_segments):
                email_body_segments = [message.snippet]

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
            if balance == DEFAULT_BALANCE or 'N/A' in balance:
                logger.info(f'Balance not found in email for rule: {rule.name}: {balance}')
                return

            balance = self._format_balance_result(balance)

            # Try to parse the balance as a float
            try:
                balance = float(balance)
                logger.info(f'Balance successfully parsed as float: {balance}')
            except Exception as ex:
                logger.info(f'Balance is not a float: {balance}')
                raise GmailBalanceSyncException(
                    f'Failed to parse balance: {balance}') from ex

            logger.info(f'Balance: {balance}')

            # Determine the bank key based on the email body
            bank_key = self._handle_account_specific_balance_sync(
                bank_key=bank_key,
                email_body_segments=email_body_segments)

            # Store the balance record
            captured = await self._bank_service.capture_balance(
                bank_key=bank_key,
                balance=float(balance),
                tokens=total_tokens,
                message_bk=message.message_id,
                sync_type=SyncType.Email)

            logger.info(f'Balance captured successfully for bank: {bank_key}')

            return captured

        except Exception as ex:
            logger.exception(f'Error parsing balance: {str(ex)}')

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

                logger.info(f'Parsing Synchrony card type')
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

        logger.info(f'GPT balance completion prompt cache key: {key}')

        cached_response = await self._cache_client.get_json(
            key=key)

        # Use cached balance completion if available
        if cached_response is not None:
            logger.info(f'Using cached GPT balance completion prompt: {cached_response}')

            return ChatGptBalanceCompletion.from_balance_response(
                balance=cached_response.get('balance'),
                usage=cached_response.get('usage'))

        # Max 5 attempts to parse balance from string
        for attempt in range(5):
            try:
                logger.info(
                    f'Parse balance from string w/ GPT: Attempt {attempt + 1}')

                # Submit the prompt to GPT and get the response
                # and tokens used
                balance, usage = await self._chat_gpt_service.get_chat_completion(
                    prompt=balance_prompt)

                logger.info(f'GPT response balance / usage: {balance} : {usage}')

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

        # Truncate the reduced message to 500 chars max not
        # to exceed GPTs token limit
        if len(value) > 500:
            value = value[:500]

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
                bank_key = BankKey.SynchronyAmazon
            # Guitar Center Card
            if SYNCHRONY_GUITAR_CENTER in email_body:
                bank_key = BankKey.SynchronyGuitarCenter
            # Sweetwater Card
            if SYNCHRONY_SWEETWATER in email_body:
                bank_key = BankKey.SynchronySweetwater

        logger.info(f'Synchrony bank key: {bank_key}')

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
                bank_key = BankKey.CapitalOneSavor
            # VentureOne
            if CAPITAL_ONE_VENTURE in email_body:
                bank_key = BankKey.CapitalOneVenture
            # QuickSilver
            if CAPITAL_ONE_QUICKSILVER in email_body:
                bank_key = BankKey.CapitalOneQuickSilver

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

        fire_task(
            self._cache_client.set_json(
                key=key,
                value=value,
                ttl=60 * 24))
