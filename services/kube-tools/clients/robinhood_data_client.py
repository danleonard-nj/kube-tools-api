import asyncio
import logging
import robin_stocks.robinhood as r
from framework.clients.cache_client import CacheClientAsync
from data.sms_inbound_repository import InboundSMSRepository
from framework.logger import get_logger
from framework.configuration import Configuration

from models.robinhood_models import RobinhoodConfig

logger = get_logger(__name__)


class RobinhoodDataClient:
    """Client for handling Robinhood data operations"""

    def __init__(
        self,
        configuration: Configuration,
        cache_client: CacheClientAsync,
        robinhood_config: RobinhoodConfig
    ):
        """
        Initialize the Robinhood data client

        Args:
            username: Robinhood username
            password: Robinhood password
            inbound_sms_repository: Repository for retrieving MFA tokens
            cache_client: Optional cache client for caching responses
        """
        self._username = robinhood_config.username
        self._password = robinhood_config.password

        # Remove SMS repository from init
        self._cache_client = cache_client

    async def login(self):
        """
        Login to Robinhood, handling 2FA if needed

        Returns:
            Dict with success status and MFA information
        """
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
            }
        except Exception as e:
            logger.error('Error during login: %s', str(e))
            return {
                'success': False,
                'error': str(e)
            }

    async def get_order_symbol_mapping(self, recent_orders):
        """
        Get mapping of instrument URLs to stock symbols for recent orders

        Args:
            recent_orders: List of recent orders to get symbols for

        Returns:
            Tuple of (order_symbol_map, cache_hits, cache_misses)
        """
        def get_order_instrument_url(order):
            """Helper function to extract instrument URL from order"""
            if hasattr(order, 'instrument') and order.instrument:
                return order.instrument if isinstance(order.instrument, str) else getattr(order.instrument, 'url', None)
            return None

        # Prefetch instrument symbols for recent orders
        instrument_urls = set()
        for order in recent_orders:
            url = get_order_instrument_url(order)
            if url:
                instrument_urls.add(url)

        order_symbol_map = {}

        for url in instrument_urls:
            try:
                logger.info(f'Attempting to fetch symbol for instrument URL: {url}')
                symbol = ''
                cache_key = f"robinhood_symbol:instrument:{url}"
                cached = await self._cache_client.get_cache(cache_key)
                if cached:
                    logger.info(f'Using cached symbol for {url}: {cached}')
                    symbol = cached
                else:
                    logger.info(f'Fetching symbol for {url} from Robinhood')
                    symbol = r.stocks.get_symbol_by_url(url)
                    logger.info(f'Fetched symbol for {url}: {symbol}')
                    await self._cache_client.set_cache(
                        cache_key,
                        symbol,
                        ttl=60)

                order_symbol_map[url] = symbol
            except Exception as ex:
                logger.error(f'Failed to fetch symbol for {url}: {ex}')
                order_symbol_map[url] = 'Unknown'

        return order_symbol_map

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
        Calculate total portfolio value from holdings data and available cash.

        Args:
            portfolio_data: Portfolio data from get_portfolio_data

        Returns:
            Total portfolio value as a float
        """
        logger.info('Calculating total portfolio value')

        try:
            # 1. Try to use total_equity from portfolio_profile if available and valid
            portfolio_profile = portfolio_data.get('portfolio_profile', {})
            total_equity = portfolio_profile.get('total_equity')
            if total_equity:
                try:
                    equity_value = float(total_equity)
                    if equity_value > 0:
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
                    except (ValueError, TypeError):
                        logger.warning('Invalid cash value for %s: %s', cash_field, cash_value)

            logger.info('Total portfolio value calculated: $%.2f', total_value)
            return total_value
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
