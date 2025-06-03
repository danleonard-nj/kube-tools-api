import asyncio
import logging
import robin_stocks.robinhood as r
from framework.clients.cache_client import CacheClientAsync
from data.sms_inbound_repository import InboundSMSRepository
from framework.logger import get_logger
from framework.configuration import Configuration

logger = get_logger(__name__)


class RobinhoodDataClient:
    """Client for handling Robinhood data operations"""

    def __init__(
        self,
        configuration: Configuration,
        inbound_sms_repository: InboundSMSRepository = None,
        cache_client: CacheClientAsync = None
    ):
        """
        Initialize the Robinhood data client

        Args:
            username: Robinhood username
            password: Robinhood password
            inbound_sms_repository: Repository for retrieving MFA tokens
            cache_client: Optional cache client for caching responses
        """
        self._username = configuration.robinhood.get('username')
        self._password = configuration.robinhood.get('password')
<<<<<<< HEAD
        # Remove SMS repository from init
=======
        self._inbound_sms_repository = inbound_sms_repository
>>>>>>> main
        self._cache_client = cache_client

    async def login(self):
        """
        Login to Robinhood, handling 2FA if needed

        Returns:
            Dict with success status and MFA information
        """
<<<<<<< HEAD
        logger.info('Attempting to login to Robinhood for user: %s', self._username)

        try:
            logger.debug('Calling r.login without MFA')
            r.login(
                username=self._username,
                password=self._password
            )
            return {
                'success': True,
                'error': None
=======
        mfa_token = None
        logger.info('Attempting to login to Robinhood for user: %s', self._username)

        try:
            try:
                logger.debug('Calling r.login without MFA')
                r.login(
                    username=self._username,
                    password=self._password
                )
                logger.info('Login successful without MFA')
            except r.robinhood.exceptions.TwoFactorRequired as e:
                logger.warning('TwoFactorRequired exception caught: %s', str(e))

                if not self._inbound_sms_repository:
                    logger.error('SMS repository not available for MFA')
                    return {
                        'success': False,
                        'mfa_required': True,
                        'error': 'MFA required but SMS repository not available'
                    }

                mfa_token = await self._get_mfa_token()

                if mfa_token:
                    logger.debug('Calling r.login with MFA token')
                    r.login(
                        username=self._username,
                        password=self._password,
                        mfa_code=mfa_token
                    )
                    logger.info('Login successful with MFA')
                else:
                    logger.error('Failed to retrieve MFA token after 5 attempts')
                    return {
                        'success': False,
                        'mfa_required': True,
                        'error': 'MFA token not received'
                    }

            logger.debug('Returning login result: success=True, mfa_required=%s', mfa_token is not None)
            return {
                'success': True,
                'mfa_required': mfa_token is not None
>>>>>>> main
            }
        except Exception as e:
            logger.error('Error during login: %s', str(e))
            return {
                'success': False,
<<<<<<< HEAD
                'error': str(e)
            }

=======
                'mfa_required': False,
                'error': str(e)
            }

    async def _get_mfa_token(self, max_attempts=5, delay_seconds=5):
        """
        Wait for and retrieve MFA token from SMS

        Args:
            max_attempts: Maximum number of attempts to check for SMS
            delay_seconds: Delay between attempts in seconds

        Returns:
            MFA token if found, None otherwise
        """
        cycles = 0
        while cycles < max_attempts:
            logger.info('Waiting for MFA SMS (attempt %d/%d)', cycles + 1, max_attempts)
            last_messages = await self._inbound_sms_repository.get_messages(limit=1)

            if last_messages:
                mfa_token = last_messages[0].body.strip()
                logger.info('Received MFA token: %s', mfa_token)
                return mfa_token

            logger.debug(f'No MFA SMS received, sleeping for {delay_seconds} seconds')
            await asyncio.sleep(delay_seconds)
            cycles += 1

        return None

>>>>>>> main
    async def get_portfolio_data(self):
        """
        Fetch comprehensive portfolio data from Robinhood

        Returns:
            Dict with portfolio data or error information
        """
        logger.info('Fetching comprehensive portfolio data')

        try:
            # Get account profile
            account_profile = r.profiles.load_account_profile()

            # Get portfolio profile
            portfolio_profile = r.profiles.load_portfolio_profile()

            # Get current holdings
            holdings = r.account.build_holdings()

            # Get positions (including options if any)
            positions = r.account.build_user_profile()

            # Get recent orders (with error handling)
            try:
                orders = r.orders.get_all_stock_orders()
                if orders:
                    orders = orders[:10]  # Last 10 orders
                else:
                    orders = []
                    logger.warning('No orders returned from get_all_stock_orders')
            except Exception as e:
                logger.warning(f'Failed to fetch orders: {str(e)}')
                orders = []

            # Get watchlist stocks for context (with error handling)
            try:
                watchlist = r.account.get_watchlist_by_name('Default')
                if not watchlist:
                    logger.warning('No watchlist found or empty watchlist')
                    watchlist = []
            except Exception as e:
                logger.warning(f'Failed to fetch watchlist: {str(e)}')
                watchlist = []

            portfolio_data = {
                'account_profile': account_profile,
                'portfolio_profile': portfolio_profile,
                'holdings': holdings,
                'positions': positions,
                'recent_orders': orders,
                'watchlist': watchlist
            }

            logger.debug('Portfolio data retrieved successfully')
            return {
                'success': True,
                'data': portfolio_data
            }

        except Exception as e:
            logger.error('Error fetching portfolio data: %s', str(e))
            return {
                'success': False,
                'error': str(e)
            }

    def calculate_total_portfolio_value(self, portfolio_data):
        """
<<<<<<< HEAD
        Calculate total portfolio value from holdings data and available cash.
=======
        Calculate total portfolio value from holdings data and available cash
>>>>>>> main

        Args:
            portfolio_data: Portfolio data from get_portfolio_data

        Returns:
            Total portfolio value as a float
        """
        logger.info('Calculating total portfolio value')

        try:
<<<<<<< HEAD
            # 1. Try to use total_equity from portfolio_profile if available and valid
            portfolio_profile = portfolio_data.get('portfolio_profile', {})
            total_equity = portfolio_profile.get('total_equity')
=======
            total_value = 0.0

            # Get account profile for cash balance
            account_profile = portfolio_data.get('account_profile', {})

            # First, try to get the total equity from portfolio profile (most accurate)
            portfolio_profile = portfolio_data.get('portfolio_profile', {})
            total_equity = portfolio_profile.get('total_equity', '0.0')
>>>>>>> main
            if total_equity:
                try:
                    equity_value = float(total_equity)
                    if equity_value > 0:
<<<<<<< HEAD
                        logger.debug('Using total equity as portfolio value: $%.2f', equity_value)
                        return equity_value
                except (ValueError, TypeError):
                    logger.warning('Invalid total equity value: %s', total_equity)

            # 2. Otherwise, sum up all holdings' market_value or (quantity * price)
            holdings = portfolio_data.get('holdings', {})
            total_value = 0.0
            for symbol, holding in holdings.items():
                try:
                    market_value = holding.get('market_value')
                    if market_value:
                        total_value += float(market_value)
                        logger.debug('Added holding %s market value: $%.2f', symbol, float(market_value))
                    else:
                        quantity = float(holding.get('quantity', 0) or 0)
                        price = float(holding.get('price', 0) or 0)
                        holding_value = quantity * price
                        total_value += holding_value
                        logger.debug('Added holding %s calculated value: %.2f * %.2f = $%.2f',
                                     symbol, quantity, price, holding_value)
                except (ValueError, TypeError) as e:
                    logger.warning('Invalid holding data for %s: %s', symbol, str(e))

            # 3. Add available cash (try multiple common fields, add the first valid one)
            account_profile = portfolio_data.get('account_profile', {})
            for cash_field in ['portfolio_cash', 'buying_power', 'cash']:
                cash_value = account_profile.get(cash_field)
                if cash_value:
                    try:
                        cash_float = float(cash_value)
                        if cash_float > 0:
                            total_value += cash_float
                            logger.debug('Added cash (%s): $%.2f', cash_field, cash_float)
                            break  # Only add the first valid cash field
=======
                        total_value = equity_value
                        logger.debug('Using total equity as portfolio value: $%.2f', equity_value)
                        return total_value
                except (ValueError, TypeError):
                    logger.warning('Invalid total equity value: %s', total_equity)

            # If no valid equity data, calculate from individual holdings
            holdings = portfolio_data.get('holdings', {})
            for symbol, holding_data in holdings.items():
                try:
                    # First try to get market_value if available
                    market_value = holding_data.get('market_value', '0.0')
                    if market_value and market_value != '0.0':
                        holding_value = float(market_value)
                        total_value += holding_value
                        logger.debug('Added holding %s market value: $%.2f', symbol, holding_value)
                    else:
                        # Calculate from quantity and price
                        quantity = holding_data.get('quantity', '0')
                        price = holding_data.get('price', '0')
                        if quantity and price:
                            quantity_float = float(quantity)
                            price_float = float(price)
                            holding_value = quantity_float * price_float
                            total_value += holding_value
                            logger.debug('Added holding %s calculated value: %.2f * %.2f = $%.2f',
                                         symbol, quantity_float, price_float, holding_value)
                except (ValueError, TypeError) as e:
                    logger.warning('Invalid holding data for %s: %s', symbol, str(e))

            # Add available cash (try multiple cash field names)
            cash_fields = ['portfolio_cash', 'buying_power', 'cash']
            cash_added = False
            for cash_field in cash_fields:
                cash_value = account_profile.get(cash_field, '0.0')
                if cash_value and cash_value != '0.0' and not cash_added:
                    try:
                        cash_float = float(cash_value)
                        total_value += cash_float
                        logger.debug('Added cash (%s): $%.2f', cash_field, cash_float)
                        cash_added = True
                        break
>>>>>>> main
                    except (ValueError, TypeError):
                        logger.warning('Invalid cash value for %s: %s', cash_field, cash_value)

            logger.info('Total portfolio value calculated: $%.2f', total_value)
            return total_value
<<<<<<< HEAD
=======

>>>>>>> main
        except Exception as e:
            logger.error('Error calculating portfolio value: %s', str(e))
            return 0.0

    async def get_account_info(self):
        """
        Get simplified account information (holdings only) from Robinhood

        Returns:
            Dict with holdings information or error
        """
        logger.info('Fetching account information for user: %s', self._username)
        try:
            account_info = r.account.build_holdings()
            if not account_info:
                logger.warning('No account information found')
                return {
                    'success': False,
                    'error': 'No account information found'
                }
            logger.debug('Account information retrieved successfully')
            return {
                'success': True,
                'data': account_info
            }
        except Exception as e:
            logger.error('Error fetching account information: %s', str(e))
            return {
                'success': False,
                'error': str(e)
            }

    async def get_cached_portfolio_data(self, ttl=3600):
        """
        Get portfolio data with caching

        Args:
            ttl: Cache time to live in seconds

        Returns:
            Dict with portfolio data or error information
        """
        if not self._cache_client:
            # If no cache client, just fetch live data
            return await self.get_portfolio_data()

        cache_key = "robinhood_account_data"
        portfolio_data = await self._cache_client.get_json(cache_key)

        if portfolio_data:
            logger.info("Using cached portfolio data")
            return portfolio_data

        # Fetch fresh data if not in cache
        logger.info("No cached data found, fetching fresh portfolio data")
        portfolio_data = await self.get_portfolio_data()

        if portfolio_data.get('success', False):
            # Cache successful responses
            await self._cache_client.set_json(cache_key, portfolio_data, ttl=ttl)

        return portfolio_data
