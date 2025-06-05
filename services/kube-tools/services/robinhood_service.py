from typing import Dict, List, Optional, Tuple, Any
from pydantic import BaseModel, SecretStr
from clients.gpt_client import GPTClient
from clients.robinhood_data_client import RobinhoodDataClient
from domain.enums import BankKey, SyncType
from services.bank_service import BankService
from services.market_research_processor import MarketResearchProcessor
from services.email_generator import EmailGenerator
from services.prompt_generator import PromptGenerator
from framework.clients.cache_client import CacheClientAsync
from utilities.utils import DateTimeUtil
from framework.logger import get_logger
from models.robinhood_models import Holding, Order, PortfolioData, DebugReport
from sib_api_v3_sdk import ApiClient, Configuration as SibConfiguration
from sib_api_v3_sdk.api.transactional_emails_api import TransactionalEmailsApi
from sib_api_v3_sdk.models import SendSmtpEmail
import shutil
import os


logger = get_logger(__name__)


class TradeAnalysis(BaseModel):
    """Model for individual trade analysis data."""
    side: str
    symbol: str
    trade_price: float
    current_price: Optional[float] = None
    gain: Optional[float] = None
    pct: Optional[float] = None
    result_status: Optional[str] = None  # 'up', 'down', 'even', or None
    outlook: str = ""  # Will be filled by GPT later
    quantity: float
    date: str
    datetime: Optional[str] = None  # New field for full datetime
    state: str


class EmailConfig(BaseModel):
    """Configuration for email settings."""
    sendinblue_api_key: SecretStr  # Secret key for Sendinblue API
    from_email: str  # Email address to send from


class RobinhoodService:
    """Service for Robinhood portfolio analysis and daily pulse reports."""

    # Constants
    CACHE_TTL_MINUTES = 60  # 1 hour
    MAX_RECENT_ORDERS = 15
    MAX_TRADE_PERFORMANCE_ORDERS = 10
    DEFAULT_EMAIL_RECIPIENT = 'dcl525@gmail.com'

    def __init__(
        self,
        robinhood_client: RobinhoodDataClient,
        gpt_client: GPTClient,
        market_research_processor: MarketResearchProcessor,
        prompt_generator: PromptGenerator,
        email_generator: EmailGenerator,
        cache_client: CacheClientAsync,
        email_config: EmailConfig,
        bank_service: BankService
    ) -> None:
        """Initialize the RobinhoodService with required dependencies."""
        self._robinhood_client = robinhood_client
        self._gpt_client = gpt_client
        self._market_research_processor = market_research_processor
        self._prompt_generator = prompt_generator
        self._email_generator = email_generator
        self._cache_client = cache_client
        self._bank_service = bank_service

        self._prompts: Dict[str, str] = {}

        # Initialize Sendinblue email client
        self._setup_email_client(email_config)

        # Performance tracking
        self.search_count = 0
        self.gpt_tokens = 0

    def _setup_email_client(self, email_config: EmailConfig) -> None:
        """Initialize Sendinblue email client configuration."""
        try:
            self._sib_api_key = email_config.sendinblue_api_key.get_secret_value()
            self._sib_sender = {"email": email_config.from_email, "name": "Kube Tools"}

            sib_config = SibConfiguration()
            sib_config.api_key['api-key'] = self._sib_api_key
            self._sib_client = ApiClient(sib_config)
            self._sib_email_api = TransactionalEmailsApi(self._sib_client)

            logger.info("Sendinblue email client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Sendinblue client: {e}")
            raise

    async def _send_email_sendinblue(self, recipient: str, subject: str, html_body: str) -> None:
        """Send email via Sendinblue API."""
        email = SendSmtpEmail(
            to=[{"email": recipient}],
            sender=self._sib_sender,
            subject=subject,
            html_content=html_body
        )

        self._sib_email_api.send_transac_email(email)
        logger.info(f"Email sent successfully to {recipient}")

    async def _get_or_fetch_portfolio_data(self) -> Optional[PortfolioData]:
        """Get portfolio data from cache or fetch fresh from Robinhood."""
        # Try to get cached data first
        portfolio_data = await self._robinhood_client.get_cached_portfolio_data(
            ttl=self.CACHE_TTL_MINUTES
        )

        if not portfolio_data or not portfolio_data.get('success', False):
            logger.info("Cache miss - fetching fresh portfolio data")

            # Login to Robinhood if not cached
            login_result = await self._robinhood_client.login()
            if not login_result.get('success', False):
                logger.error('Failed to login to Robinhood')
                return None

            # Fetch fresh portfolio data
            portfolio_data = await self._robinhood_client.get_portfolio_data()
            if not portfolio_data.get('success', False):
                logger.error('Failed to fetch portfolio data')
                return None

            # Cache the fresh data
            await self._cache_client.set_json(
                "robinhood_account_data",
                portfolio_data,
                ttl=self.CACHE_TTL_MINUTES
            )
        else:
            logger.info("Using cached portfolio data")

        # Parse and validate the portfolio data
        portfolio_obj = PortfolioData.model_validate(portfolio_data['data'])
        return portfolio_obj

    async def _capture_portfolio_balance(self, portfolio_obj: PortfolioData) -> None:
        """Extract and store portfolio balance for tracking."""
        try:
            portfolio_balance = round(float(portfolio_obj.portfolio_profile.last_core_equity), 2)
            await self._bank_service.capture_balance(
                bank_key=BankKey.Robinhood,
                balance=portfolio_balance,
                sync_type=str(SyncType.Robinhood)
            )
            logger.info(f"Portfolio balance captured: ${portfolio_balance:,.2f}")
        except (ValueError, TypeError, AttributeError) as e:
            logger.error(f"Failed to capture portfolio balance - data format issue: {e}", exc_info=True)

    async def _get_market_research_and_summary(self, portfolio_data: Dict[str, Any]) -> Any:
        """Fetch and summarize market research data."""
        try:
            logger.info('Fetching market research and current news')
            market_research = await self._market_research_processor.get_market_research_data(portfolio_data)

            # Summarize the research data
            summarized_market_research = await self._market_research_processor.summarize_market_research(market_research)

            # Store prompts for debugging
            self._prompts.update(self._market_research_processor.get_prompts())

            return summarized_market_research
        except Exception as e:
            logger.error(f"Failed to get market research: {e}")
            raise

    async def _enrich_orders_with_symbols(self, recent_orders: List[Order]) -> List[Order]:
        """Enrich order objects with symbol information."""
        try:
            # Get symbol mapping from data client
            order_symbol_map = await self._robinhood_client.get_order_symbol_mapping(recent_orders)

            # Apply symbol mapping to orders
            for order in recent_orders:
                instrument_url = self._extract_instrument_url(order)
                if instrument_url and instrument_url in order_symbol_map:
                    order.symbol = order_symbol_map[instrument_url]
                else:
                    order.symbol = 'Unknown'
                    logger.warning(f"Could not find symbol for order {order.id}")

            return recent_orders
        except Exception as e:
            logger.error(f"Failed to enrich orders with symbols: {e}", exc_info=True)
            # Return orders with 'Unknown' symbols as fallback
            for order in recent_orders:
                if not hasattr(order, 'symbol'):
                    order.symbol = 'Unknown'
            return recent_orders

    def _extract_instrument_url(self, order: Order) -> Optional[str]:
        """Extract instrument URL from order object safely."""
        if not hasattr(order, 'instrument') or not order.instrument:
            return None

        if isinstance(order.instrument, str):
            return order.instrument

        return getattr(order.instrument, 'url', None)

    def _build_trade_performance_summary(
        self,
        recent_orders: List[Order],
        holdings: Dict[str, Holding]
    ) -> Tuple[List[TradeAnalysis], Dict[str, Any]]:
        """Build trade performance summary from recent orders."""
        trade_rows = []
        total_gain = 0.0
        total_loss = 0.0
        win_count = 0
        loss_count = 0

        # Process the most recent filled orders
        filled_orders = [order for order in recent_orders[:self.MAX_TRADE_PERFORMANCE_ORDERS]
                         if order.state.upper() == 'FILLED']

        for order in filled_orders:
            try:
                trade_data = self._analyze_single_trade(order, holdings)
                trade_rows.append(trade_data)

                # Update performance statistics
                gain = trade_data.gain
                if gain is not None:
                    if gain > 0:
                        total_gain += gain
                        win_count += 1
                    elif gain < 0:
                        total_loss += abs(gain)
                        loss_count += 1

            except Exception as e:
                logger.error(f"Failed to analyze trade for order {order.id}: {e}", exc_info=True)
                continue

        stats = {
            'total_gain': total_gain,
            'total_loss': total_loss,
            'win_count': win_count,
            'loss_count': loss_count,
            'trade_count': len(trade_rows),
        }

        return trade_rows, stats

    def _analyze_single_trade(self, order: Order, holdings: Dict[str, Holding]) -> TradeAnalysis:
        """Analyze a single trade order for performance metrics."""
        side = order.side.capitalize()
        symbol = getattr(order, 'symbol', 'Unknown')
        qty = float(order.quantity or 0)
        trade_price = float(order.price or 0)

        # Initialize default values
        avg_buy_price = None
        gain = None
        current_price = None
        result_status = None
        pct = None

        # Calculate gain/loss if holding information is available
        holding = holdings.get(symbol)
        if holding:
            try:
                avg_buy_price = float(holding.average_buy_price)
                current_price = float(holding.price)

                if side == 'Sell':
                    gain = (trade_price - avg_buy_price) * qty
                else:
                    gain = (current_price - trade_price) * qty

            except (ValueError, TypeError) as e:
                logger.warning(f"Could not calculate gain for {symbol}: {e}")

        # Calculate percentage and status
        if gain is not None and qty > 0 and trade_price > 0:
            pct = (gain / (trade_price * qty)) * 100
            if gain > 0:
                result_status = 'up'
            elif gain < 0:
                result_status = 'down'
            else:
                result_status = 'even'

        return TradeAnalysis(
            side=side,
            symbol=symbol,
            trade_price=trade_price,
            current_price=current_price,
            gain=gain,
            pct=pct,
            result_status=result_status,
            outlook='',  # Will be filled by GPT later
            quantity=qty,
            date=(order.created_at or '')[:10],
            datetime=order.created_at,  # Store full datetime string
            state=order.state,
        )

    async def _generate_trade_outlooks(
        self,
        trade_rows: List[TradeAnalysis],
        portfolio_obj: PortfolioData,
        summarized_market_research: Any
    ) -> List[TradeAnalysis]:
        """Generate AI-powered outlooks for individual trades."""
        # Build lookups for efficient data access
        stock_news_lookup = self._build_stock_news_lookup(summarized_market_research)
        sector_lookup, fallback_sector_summary = self._build_sector_lookup(summarized_market_research)

        for trade in trade_rows:
            try:
                outlook = await self._generate_single_trade_outlook(
                    trade, portfolio_obj, stock_news_lookup, sector_lookup, fallback_sector_summary
                )
                trade.outlook = outlook
            except Exception as e:
                logger.error(f"Failed to generate outlook for trade {trade.symbol}: {e}", exc_info=True)
                trade.outlook = f"(Could not generate outlook: {str(e)})"

        return trade_rows

    def _build_stock_news_lookup(self, summarized_market_research: Any) -> Dict[str, Optional[str]]:
        """Build a lookup dictionary for stock news by symbol."""
        stock_news_lookup = {}
        if hasattr(summarized_market_research, 'stock_news') and summarized_market_research.stock_news:
            stock_news_lookup = {
                k: v[0].snippet if v else None
                for k, v in summarized_market_research.stock_news.items()
            }
        return stock_news_lookup

    def _build_sector_lookup(self, summarized_market_research: Any) -> Tuple[Dict[str, str], Optional[str]]:
        """Build sector lookup and fallback summary."""
        sector_summaries = getattr(summarized_market_research, 'sector_analysis', [])
        sector_lookup = {}

        for section in sector_summaries:
            if section.title:
                sector_lookup[section.title.lower()] = section.snippet

        fallback_sector_summary = sector_summaries[0].snippet if sector_summaries else None
        return sector_lookup, fallback_sector_summary

    async def _generate_single_trade_outlook(
        self,
        trade: TradeAnalysis,
        portfolio_obj: PortfolioData,
        stock_news_lookup: Dict[str, Optional[str]],
        sector_lookup: Dict[str, str],
        fallback_sector_summary: Optional[str]
    ) -> str:
        """Generate outlook for a single trade using AI."""
        symbol = trade.symbol

        # Get news summary for this symbol
        news_summary = stock_news_lookup.get(symbol)

        # Get sector information
        holding = portfolio_obj.holdings.get(symbol) if hasattr(portfolio_obj, 'holdings') else None
        sector_summary = None

        if holding and hasattr(holding, 'sector') and holding.sector:
            # Try to match sector summary by sector name
            for key, snippet in sector_lookup.items():
                if holding.sector.lower() in key:
                    sector_summary = snippet
                    break

        if not sector_summary:
            sector_summary = fallback_sector_summary

        # Generate trade outlook prompt
        trade_prompt = self._prompt_generator.generate_trade_outlook_prompt(
            trade=trade.model_dump(),
            news_summary=news_summary,
            sector_summary=sector_summary
        )

        # Get AI-generated outlook
        outlook = await self._gpt_client.generate_completion(
            prompt=trade_prompt,
            model="gpt-4o-mini",
            temperature=0.6,
            use_cache=False
        )

        return outlook

    async def _generate_overall_trade_outlook(
        self,
        trade_rows: List[TradeAnalysis],
        trade_stats: Dict[str, Any]
    ) -> str:
        """Generate overall trade performance outlook using AI."""
        trade_outlook_prompt = self._prompt_generator.generate_trade_outlook_summary_prompt(
            trade_rows=[trade.model_dump() for trade in trade_rows],
            trade_stats=trade_stats
        )

        trade_outlook = await self._gpt_client.generate_completion(
            prompt=trade_outlook_prompt,
            model="gpt-4o-mini",
            temperature=0.6,
            use_cache=False
        )

        return trade_outlook

    async def _generate_main_pulse_analysis(
        self,
        portfolio_obj: PortfolioData,
        summarized_market_research: Any,
        order_symbol_map: Dict[str, str]
    ) -> str:
        """Generate the main daily pulse analysis using AI."""
        try:
            # Compile prompt for GPT analysis
            pulse_prompt = await self._prompt_generator.compile_daily_pulse_prompt_with_symbols(
                portfolio_obj, summarized_market_research, order_symbol_map
            )
            self._prompts['pulse_prompt'] = pulse_prompt

            # Generate analysis using GPT
            pulse_analysis = await self._gpt_client.generate_completion(
                prompt=pulse_prompt,
                model="gpt-4o",
                temperature=0.7,
                use_cache=False
            )

            return pulse_analysis
        except Exception as e:
            logger.error(f"Failed to generate main pulse analysis: {e}")
            raise

    async def _send_pulse_emails(
        self,
        pulse_analysis: str,
        portfolio_obj: PortfolioData,
        summarized_market_research: Any,
        trade_rows: List[TradeAnalysis],
        trade_outlook: str,
        market_research: Any
    ) -> None:
        """Send daily pulse and debug emails."""
        # Generate and send main pulse email
        html_body = self._email_generator.generate_daily_pulse_html_email(
            analysis=pulse_analysis,
            portfolio_summary=portfolio_obj,
            market_research=summarized_market_research,
            trade_performance=[trade.model_dump() for trade in trade_rows],
            trade_outlook=trade_outlook
        )

        subject = self._email_generator.generate_daily_pulse_subject()
        await self._send_email_sendinblue(
            recipient=self.DEFAULT_EMAIL_RECIPIENT,
            subject=subject,
            html_body=html_body
        )

        # Send debug email
        await self._send_debug_email(pulse_analysis, portfolio_obj, market_research)

    async def _send_debug_email(
        self,
        pulse_analysis: str,
        portfolio_obj: PortfolioData,
        market_research: Any
    ) -> None:
        """Send admin debug email with detailed information."""
        try:
            debug_report = DebugReport(
                portfolio_data=portfolio_obj,
                market_research=market_research,
                prompts=self._prompts,
                gpt_analysis=pulse_analysis,
                sources={}
            )

            stats = {
                'search_count': self.search_count,
                'gpt_tokens': self.gpt_tokens
            }

            html_debug = self._email_generator.generate_admin_debug_html_report(debug_report, stats)
            await self._send_email_sendinblue(
                recipient=self.DEFAULT_EMAIL_RECIPIENT,
                subject='ADMIN DEBUG: Pulse Full Debug Info',
                html_body=html_debug
            )

            # Clean up stored prompts
            self._market_research_processor.clear_prompts()
            self._prompts = {}

        except Exception as e:
            logger.error(f"Failed to send admin debug report email: {e}", exc_info=True)

    async def generate_daily_pulse(self) -> Dict[str, Any]:
        """
        Generate a comprehensive daily pulse report for Robinhood account.

        Returns dict with success status and generated data.
        """
        logger.info('Starting daily pulse report generation')

        try:
            self._gpt_client.count = 0  # Reset GPT call count for this run
            if os.path.exists('./prompts'):
                shutil.rmtree('./prompts')
            os.makedirs('./prompts', exist_ok=True)

            # Step 1: Get portfolio data
            portfolio_obj = await self._get_or_fetch_portfolio_data()
            if not portfolio_obj:
                return {'success': False, 'error': 'Failed to fetch portfolio data'}

            # Step 2: Capture portfolio balance
            await self._capture_portfolio_balance(portfolio_obj)

            # Step 3: Get market research (fetch ONCE)
            raw_market_research = await self._market_research_processor.get_market_research_data(
                portfolio_obj.model_dump()
            )
            summarized_market_research = await self._get_market_research_and_summary(
                portfolio_obj.model_dump()
            )

            # Step 4: Process recent orders
            recent_orders = portfolio_obj.recent_orders[:self.MAX_RECENT_ORDERS]
            recent_orders = await self._enrich_orders_with_symbols(recent_orders)

            # Step 5: Generate trade performance analysis
            trade_rows, trade_stats = self._build_trade_performance_summary(
                recent_orders, portfolio_obj.holdings
            )

            # Step 6: Generate AI-powered trade outlooks
            trade_rows = await self._generate_trade_outlooks(
                trade_rows, portfolio_obj, summarized_market_research
            )

            # Step 7: Generate overall trade outlook
            trade_outlook = await self._generate_overall_trade_outlook(trade_rows, trade_stats)

            # Step 8: Generate main pulse analysis
            order_symbol_map = await self._robinhood_client.get_order_symbol_mapping(recent_orders)
            pulse_analysis = await self._generate_main_pulse_analysis(
                portfolio_obj, summarized_market_research, order_symbol_map
            )

            # Step 9: Send emails (use the same raw_market_research)
            await self._send_pulse_emails(
                pulse_analysis, portfolio_obj, summarized_market_research,
                trade_rows, trade_outlook, raw_market_research
            )

            logger.info('Daily pulse report generated successfully')

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
            logger.error(f"Failed to generate daily pulse: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    async def login(self) -> Dict[str, Any]:
        """Login to Robinhood using RobinhoodDataClient."""
        return await self._robinhood_client.login()

    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information from Robinhood using RobinhoodDataClient."""
        return await self._robinhood_client.get_account_info()
