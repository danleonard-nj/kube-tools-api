from framework.configuration import Configuration
from clients.gpt_client import GPTClient
from clients.robinhood_data_client import RobinhoodDataClient
from services.market_research_processor import MarketResearchProcessor
from services.email_generator import EmailGenerator
from services.prompt_generator import PromptGenerator
from clients.google_search_client import GoogleSearchClient
from data.sms_inbound_repository import InboundSMSRepository
from framework.clients.cache_client import CacheClientAsync
from utilities.utils import DateTimeUtil
from framework.logger import get_logger
from models.robinhood_models import PortfolioData, MarketResearch, DebugReport
from sib_api_v3_sdk import ApiClient, Configuration as SibConfiguration
from sib_api_v3_sdk.api.transactional_emails_api import TransactionalEmailsApi
from sib_api_v3_sdk.models import SendSmtpEmail


logger = get_logger(__name__)


class RobinhoodService:
    def __init__(
        self,
        robinhood_client: RobinhoodDataClient,
        gpt_client: GPTClient,
        market_research_processor: MarketResearchProcessor,
        prompt_generator: PromptGenerator,
        email_generator: EmailGenerator,
        cache_client: CacheClientAsync,
        configuration: Configuration
    ):
        self._username = configuration.robinhood.get('username')
        self._password = configuration.robinhood.get('password')
        self._robinhood_client = robinhood_client
        self._gpt_client = gpt_client
        self._market_research_processor = market_research_processor
        self._prompt_generator = prompt_generator
        self._email_generator = email_generator
        self._cache_client = cache_client
        self._configuration = configuration

        self._prompts = {}

        # Sendinblue setup
        self._sib_api_key = configuration.email.get('sendinblue_api_key')
        self._sib_sender = {"email": configuration.email.get('from_email', configuration.email.get('from_email')), "name": "Kube Tools"}
        sib_config = SibConfiguration()
        sib_config.api_key['api-key'] = self._sib_api_key
        self._sib_client = ApiClient(sib_config)
        self._sib_email_api = TransactionalEmailsApi(self._sib_client)

        # Stats tracking
        self.cache_hits = 0
        self.cache_misses = 0
        self.search_count = 0
        self.gpt_tokens = 0

    async def _send_email_sendinblue(self, recipient, subject, html_body):
        email = SendSmtpEmail(
            to=[{"email": recipient}],
            sender=self._sib_sender,
            subject=subject,
            html_content=html_body
        )
        try:
            self._sib_email_api.send_transac_email(email)
            logger.info(f"Email sent to {recipient} via Sendinblue.")
        except Exception as e:
            logger.error(f"Failed to send email via Sendinblue: {e}")

    async def generate_daily_pulse(self) -> dict:
        """Generate a daily pulse report for Robinhood account using OpenAI GPT-4o"""
        logger.info('Generating daily pulse report for user: %s', self._username)

        try:
            # Use RobinhoodDataClient to get cached or fresh portfolio data
            portfolio_data = await self._robinhood_client.get_cached_portfolio_data(ttl=3600)
            if not portfolio_data or not portfolio_data.get('success', False):
                # Login to Robinhood
                login_result = await self._robinhood_client.login()
                if not login_result.get('success', False):
                    logger.error('Failed to login to Robinhood')
                    return {
                        'success': False,
                        'error': 'Failed to login to Robinhood'
                    }
                portfolio_data = await self._robinhood_client.get_portfolio_data()
                if not portfolio_data.get('success', False):
                    logger.error('Failed to fetch portfolio data')
                    return {
                        'success': False,
                        'error': 'Failed to fetch portfolio data'
                    }
                # Cache the portfolio data for 1 hour
                await self._cache_client.set_json(
                    "robinhood_account_data",
                    portfolio_data,
                    ttl=3600
                )

            # Directly parse the raw data with the updated models
            portfolio_obj = PortfolioData.model_validate(portfolio_data['data'])

            # Fetch market research and news data using local method (with RSS support)
            logger.info('Fetching market research and current news')
            market_research = await self._market_research_processor.get_market_research_data(portfolio_obj.model_dump())

            # Summarize market research using MarketResearchProcessor
            summarized_market_research = await self._market_research_processor.summarize_market_research(market_research)
            # Convert to Pydantic MarketResearch
            self._prompts = self._market_research_processor.get_prompts()

            def get_order_instrument_url(order):
                """Helper function to extract instrument URL from order"""
                if hasattr(order, 'instrument') and order.instrument:
                    return order.instrument if isinstance(order.instrument, str) else getattr(order.instrument, 'url', None)
                return None

            # Prefetch instrument symbols for recent orders (now 15)
            recent_orders = portfolio_obj.recent_orders[:15]
            instrument_urls = set()
            for order in recent_orders:
                url = get_order_instrument_url(order)
                if url:
                    instrument_urls.add(url)

            order_symbol_map = {}
            import robin_stocks.robinhood as r
            for url in instrument_urls:
                try:
                    logger.info(f'Attempting to fetch symbol for instrument URL: {url}')
                    symbol = ''
                    cache_key = f"robinhood_symbol:instrumnet:{url}"
                    cached = await self._cache_client.get_cache(cache_key)
                    if cached:
                        logger.info(f'Using cached symbol for {url}: {cached}')
                        symbol = cached
                        self.cache_hits += 1
                    else:
                        logger.info(f'Fetching symbol for {url} from Robinhood')
                        symbol = r.stocks.get_symbol_by_url(url)
                        logger.info(f'Fetched symbol for {url}: {symbol}')
                        self.cache_misses += 1
                        await self._cache_client.set_cache(
                            cache_key,
                            symbol,
                            ttl=60)

                    order_symbol_map[url] = symbol
                except Exception as ex:
                    logger.error(f'Failed to fetch symbol for {url}: {ex}')
                    order_symbol_map[url] = 'Unknown'

            for order in recent_orders:
                order.symbol = order_symbol_map.get(get_order_instrument_url(order), 'Unknown')

            # Compile prompt for GPT-4o using PromptGenerator (async version)
            pulse_prompt = await self._prompt_generator.compile_daily_pulse_prompt_with_symbols(
                portfolio_obj, summarized_market_research, order_symbol_map
            )
            self._prompts['pulse_prompt'] = pulse_prompt

            # Use GPTClient for main analysis
            pulse_analysis = await self._gpt_client.generate_completion(
                prompt=pulse_prompt,
                model="gpt-4o",
                temperature=0.7,
                use_cache=False
            )
            # Try to count tokens if possible
            if hasattr(self._gpt_client, 'last_token_usage'):
                self.gpt_tokens += getattr(self._gpt_client, 'last_token_usage', 0)

            # Generate and send the daily pulse email using EmailGenerator
            html_body = self._email_generator.generate_daily_pulse_html_email(
                analysis=pulse_analysis,
                portfolio_summary=portfolio_obj,
                market_research=summarized_market_research
            )
            subject = self._email_generator.generate_daily_pulse_subject()
            await self._send_email_sendinblue(
                recipient='dcl525@gmail.com',
                subject=subject,
                html_body=html_body
            )

            # Send admin debug email
            try:
                debug_report = DebugReport(
                    portfolio_data=portfolio_obj,
                    # Use the original, unsummarized market_research for debug so links are preserved
                    market_research=market_research,  # <-- changed from summarized_market_research_obj
                    prompts=self._prompts,
                    gpt_analysis=pulse_analysis,
                    sources={}
                )
                # Collect stats (replace with real tracking if available)
                stats = {
                    'cache_hits': getattr(self, 'cache_hits', 0),
                    'cache_misses': getattr(self, 'cache_misses', 0),
                    'search_count': getattr(self, 'search_count', 0),
                    'gpt_tokens': getattr(self, 'gpt_tokens', 0),
                }
                html_debug = self._email_generator.generate_admin_debug_html_report(debug_report, stats)
                await self._send_email_sendinblue(
                    recipient='dcl525@gmail.com',
                    subject='ADMIN DEBUG: Pulse Full Debug Info',
                    html_body=html_debug
                )
                self._market_research_processor.clear_prompts()
                self._prompts = {}
            except Exception as ex:
                logger.error("Failed to send admin debug report email")
                logger.error(str(ex), exc_info=True)

            return {
                'success': True,
                'data': {
                    'analysis': pulse_analysis,
                    'portfolio_summary': portfolio_obj.model_dump(),
                    'generated_at': DateTimeUtil.get_iso_date(),
                    'market_research': summarized_market_research.model_dump(),
                }
            }

        except Exception as e:
            logger.error('Error generating daily pulse: %s', str(e))
            return {
                'success': False,
                'error': str(e)
            }

    async def login(self) -> dict:
        """Login to Robinhood using RobinhoodDataClient"""
        return await self._robinhood_client.login()

    async def get_account_info(self) -> dict:
        """Get account information from Robinhood using RobinhoodDataClient"""
        return await self._robinhood_client.get_account_info()
