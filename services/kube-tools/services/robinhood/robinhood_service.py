from typing import Dict, List, Optional, Tuple, Any, Set, Set
from pydantic import BaseModel, SecretStr, Field
from abc import ABC, abstractmethod
from dataclasses import dataclass
import asyncio
import time
from clients.gpt_client import GPTClient
from clients.robinhood_data_client import RobinhoodDataClient
from domain.enums import BankKey, SyncType
from domain.gpt import GPTModel
from models.email_config import EmailConfig
from services.bank_service import BankService
from framework.clients.cache_client import CacheClientAsync
from services.robinhood.email_generator import EmailGenerator
from services.robinhood.market_research_processor import MarketResearchProcessor
from services.robinhood.prompt_generator import PromptGenerator
from utilities.utils import DateTimeUtil
from framework.logger import get_logger
from models.robinhood_models import Holding, MarketResearchSummary, Order, PortfolioData, DebugReport, RobinhoodConfig
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


class StageResult(BaseModel):
    """Result of a pipeline stage execution."""
    success: bool = True
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    can_continue: bool = True
    execution_time_ms: float = 0.0

    def add_error(self, error: str, critical: bool = True) -> None:
        """Add an error to the result."""
        self.errors.append(error)
        self.success = False
        if critical:
            self.can_continue = False

    def add_warning(self, warning: str) -> None:
        """Add a warning to the result."""
        self.warnings.append(warning)


class PipelineConfig(BaseModel):
    """Configuration for pipeline execution."""
    skip_stages: Set[str] = Field(default_factory=set)
    retry_config: Dict[str, int] = Field(default_factory=dict)  # stage_name -> max_retries
    fail_fast: bool = False
    max_recent_orders: int = 15
    max_trade_performance_orders: int = 10
    cache_ttl_minutes: int = 60
    robinhood_config: RobinhoodConfig = None


class PulseContext(BaseModel):
    """Context object that flows through the pipeline stages."""
    # Configuration
    config: PipelineConfig = Field(default_factory=PipelineConfig)

    # Input data
    portfolio_obj: Optional[PortfolioData] = None
    raw_market_research: Optional[Any] = None

    # Processed data
    summarized_market_research: Optional[Any] = None
    enriched_orders: List[Order] = Field(default_factory=list)
    trade_analysis: List[TradeAnalysis] = Field(default_factory=list)
    trade_stats: Dict[str, Any] = Field(default_factory=dict)
    trade_outlook: str = ""
    pulse_analysis: str = ""
    order_symbol_map: Dict[str, str] = Field(default_factory=dict)

    # Execution metadata
    stage_results: Dict[str, StageResult] = Field(default_factory=dict)
    performance_metrics: Dict[str, float] = Field(default_factory=dict)
    prompts: Dict[str, str] = Field(default_factory=dict)
    gpt_tokens: int = 0
    search_count: int = 0

    # Computed properties
    @property
    def has_critical_errors(self) -> bool:
        """Check if any stage has critical errors."""
        return any(not result.can_continue for result in self.stage_results.values())

    @property
    def total_execution_time(self) -> float:
        """Total execution time across all stages."""
        return sum(result.execution_time_ms for result in self.stage_results.values())

    def add_stage_result(self, stage_name: str, result: StageResult) -> None:
        """Add a stage result to the context."""
        self.stage_results[stage_name] = result

    def should_skip_stage(self, stage_name: str) -> bool:
        """Check if a stage should be skipped."""
        return stage_name in self.config.skip_stages

    class Config:
        arbitrary_types_allowed = True


class PipelineStage(ABC):
    """Abstract base class for pipeline stages."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def execute(self, context: PulseContext) -> StageResult:
        """Execute the stage logic."""
        pass

    async def run(self, context: PulseContext) -> StageResult:
        """Run the stage with timing and error handling."""
        if context.should_skip_stage(self.name):
            result = StageResult(success=True)
            result.warnings.append(f"Stage {self.name} was skipped")
            return result

        start_time = time.time()
        try:
            result = await self.execute(context)
            result.execution_time_ms = (time.time() - start_time) * 1000
            return result
        except Exception as e:
            logger.error(f"Stage {self.name} failed: {e}", exc_info=True)
            result = StageResult()
            result.add_error(f"Stage {self.name} failed: {str(e)}")
            result.execution_time_ms = (time.time() - start_time) * 1000
            return result


class DomainStage(PipelineStage):
    """Base class for domain-specific stages that need service dependencies."""

    def __init__(self, name: str, service: 'RobinhoodService'):
        super().__init__(name)
        self.service = service


class InitializationStage(DomainStage):
    """Initialize the pipeline environment."""

    async def execute(self, context: PulseContext) -> StageResult:
        result = StageResult()
        try:
            # Reset GPT call count
            self.service._gpt_client.count = 0

            # Clean up and create prompts directory
            if os.path.exists('./prompts'):
                shutil.rmtree('./prompts')
            os.makedirs('./prompts', exist_ok=True)

            logger.info('Pipeline initialization completed')
        except Exception as e:
            result.add_error(f"Initialization failed: {str(e)}")

        return result


class FetchPortfolioStage(DomainStage):
    """Fetch and validate portfolio data from cache or API."""

    async def execute(self, context: PulseContext) -> StageResult:
        result = StageResult()

        try:
            # Try to get cached data first
            portfolio_data = await self.service._robinhood_client.get_cached_portfolio_data(
                ttl=context.config.cache_ttl_minutes
            )

            if not portfolio_data or not portfolio_data.get('success', False):
                logger.info("Cache miss - fetching fresh portfolio data")

                # Login to Robinhood if not cached
                login_result = await self.service._robinhood_client.login()
                if not login_result.get('success', False):
                    result.add_error('Failed to login to Robinhood')
                    return result

                # Fetch fresh portfolio data
                portfolio_data = await self.service._robinhood_client.get_portfolio_data()
                if not portfolio_data.get('success', False):
                    result.add_error('Failed to fetch portfolio data')
                    return result

                # Cache the fresh data
                await self.service._cache_client.set_json(
                    "robinhood_account_data",
                    portfolio_data,
                    ttl=context.config.cache_ttl_minutes
                )
            else:
                logger.info("Using cached portfolio data")

            # Parse and validate the portfolio data
            context.portfolio_obj = PortfolioData.model_validate(portfolio_data['data'])
            logger.info("Portfolio data fetched and validated successfully")

        except Exception as e:
            result.add_error(f"Failed to fetch portfolio data: {str(e)}")

        return result


class CaptureBalanceStage(DomainStage):
    """Capture and store the current portfolio balance."""

    async def execute(self, context: PulseContext) -> StageResult:
        result = StageResult()

        if not context.portfolio_obj:
            result.add_error("No portfolio data available for balance capture")
            return result

        try:
            # portfolio_balance = round(float(context.portfolio_obj.portfolio_profile.last_core_equity), 2)
            # await self.service._bank_service.capture_balance(
            #     bank_key=BankKey.Robinhood,
            #     balance=portfolio_balance,
            #     sync_type=str(SyncType.Robinhood)
            # )
            # logger.info(f"Portfolio balance captured: ${portfolio_balance:,.2f}")
            pass

        except (ValueError, TypeError, AttributeError) as e:
            result.add_error(f"Failed to capture portfolio balance - data format issue: {str(e)}")

        return result


class FetchMarketResearchStage(DomainStage):
    """Retrieve raw market research data using market research pipeline."""

    async def execute(self, context: PulseContext) -> StageResult:
        result = StageResult()

        if not context.portfolio_obj:
            result.add_error("No portfolio data available for market research")
            return result

        try:
            logger.info('Fetching market research data via market research pipeline')

            # Market research processor runs its own pipeline internally
            context.raw_market_research = await self.service._market_research_processor.get_market_research_data(
                context.portfolio_obj.model_dump(),
                context.config.robinhood_config
            )

            # Market research pipeline metrics can be captured here
            research_metrics = getattr(self.service._market_research_processor, '_last_pipeline_metrics', {})
            if research_metrics:
                context.performance_metrics['market_research_pipeline'] = research_metrics

        except Exception as e:
            # Market research failure shouldn't kill the main pipeline
            result.add_warning(f"Market research pipeline failed: {str(e)}")
            # Provide fallback empty research data
            context.raw_market_research = self._create_empty_market_research()

        return result

    def _create_empty_market_research(self):
        """Create empty market research data as fallback."""
        from models.robinhood_models import MarketResearch
        return MarketResearch.model_validate({
            'market_conditions': [],
            'stock_news': {},
            'sector_analysis': [],
            'search_errors': ['Market research pipeline unavailable']
        })


class SummarizeMarketResearchStage(DomainStage):
    """Summarize and structure market research using market research pipeline."""

    async def execute(self, context: PulseContext) -> StageResult:
        result = StageResult()

        if not context.raw_market_research:
            result.add_error("No raw market research data available for summarization")
            return result

        try:
            logger.info('Summarizing market research data via market research pipeline')

            portfolio_data = context.portfolio_obj.model_dump() if context.portfolio_obj else {}
            context.summarized_market_research = await self.service._market_research_processor.summarize_market_research(
                context.raw_market_research,
                portfolio_data
            )

            # Store prompts for debugging (from market research pipeline)
            research_prompts = self.service._market_research_processor.get_prompts()
            context.prompts.update(research_prompts)

            # Capture market research pipeline metrics
            summary_metrics = getattr(self.service._market_research_processor, '_last_summary_metrics', {})
            if summary_metrics:
                context.performance_metrics['market_research_summary_pipeline'] = summary_metrics

            if context.summarized_market_research:
                portfolio_sections = context.summarized_market_research.portfolio_summary
                trading_sections = context.summarized_market_research.trading_summary

                logger.info(f"Market research summarization completed:")
                logger.info(f"  - Portfolio sections: {len(portfolio_sections)}")
                logger.info(f"  - Trading sections: {len(trading_sections)}")

                # Log if structured data was detected
                for section in portfolio_sections:
                    if isinstance(section.data, dict):
                        logger.info(f"  - ✅ Portfolio structured data detected: {list(section.data.keys())}")

                for section in trading_sections:
                    if isinstance(section.data, dict):
                        logger.info(f"  - ✅ Trading structured data detected: {list(section.data.keys())}")

        except Exception as e:
            result.add_warning(f"Market research summarization pipeline failed: {str(e)}")
            # Provide fallback empty summary
            context.summarized_market_research = self._create_empty_market_research_summary()

        return result


class EnrichOrdersStage(DomainStage):
    """Enrich recent orders with symbol information."""

    async def execute(self, context: PulseContext) -> StageResult:
        result = StageResult()

        if not context.portfolio_obj:
            result.add_error("No portfolio data available for order enrichment")
            return result

        try:
            recent_orders = context.portfolio_obj.recent_orders[:context.config.max_recent_orders]
            context.enriched_orders = await self._enrich_orders_with_symbols(recent_orders)

            # Also build order symbol map for later use
            context.order_symbol_map = await self.service._robinhood_client.get_order_symbol_mapping(
                context.enriched_orders
            )

        except Exception as e:
            result.add_error(f"Failed to enrich orders: {str(e)}")

        return result

    async def _enrich_orders_with_symbols(self, recent_orders: List[Order]) -> List[Order]:
        """Enrich order objects with symbol information."""
        try:
            # Get symbol mapping from data client
            order_symbol_map = await self.service._robinhood_client.get_order_symbol_mapping(recent_orders)

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


class TradePerformanceStage(DomainStage):
    """Analyze recent trades for performance metrics."""

    async def execute(self, context: PulseContext) -> StageResult:
        result = StageResult()

        if not context.enriched_orders or not context.portfolio_obj:
            result.add_error("Missing required data for trade performance analysis")
            return result

        try:
            context.trade_analysis, context.trade_stats = self._build_trade_performance_summary(
                context.enriched_orders, context.portfolio_obj.holdings
            )

        except Exception as e:
            result.add_error(f"Failed to analyze trade performance: {str(e)}")

        return result

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
        filled_orders = [order for order in recent_orders[:self.service.MAX_TRADE_PERFORMANCE_ORDERS]
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


class TradeOutlooksStage(DomainStage):
    """Generate AI-powered outlooks for individual trades."""

    async def execute(self, context: PulseContext) -> StageResult:
        result = StageResult()

        if not context.trade_analysis or not context.portfolio_obj or not context.summarized_market_research:
            result.add_error("Missing required data for trade outlook generation")
            return result

        try:
            # Build lookups for efficient data access
            stock_news_lookup = self._build_stock_news_lookup(context.summarized_market_research)
            sector_lookup, fallback_sector_summary = self._build_sector_lookup(context.summarized_market_research)

            def get_trade_key(trade): return f'{trade.symbol}-{trade.datetime}'

            results = dict()
            tasks = []
            sem = asyncio.Semaphore(10)  # Limit concurrent AI calls

            async def generate_single_trade_outlook(**kwargs) -> None:
                key = get_trade_key(kwargs['trade'])
                logger.info(f'Generating outlook for trade {key}')
                result = await self._generate_single_trade_outlook(
                    **kwargs)
                results[key] = result

            for trade in context.trade_analysis:
                if not trade.symbol or not trade.datetime:
                    logger.warning(f"Skipping trade with missing symbol or datetime: {trade}")
                    continue

                tasks.append(generate_single_trade_outlook(
                    trade=trade,
                    portfolio_obj=context.portfolio_obj,
                    stock_news_lookup=stock_news_lookup,
                    sector_lookup=sector_lookup,
                    fallback_sector_summary=fallback_sector_summary
                ))

            await asyncio.gather(*tasks)

            for trade in context.trade_analysis:
                try:
                    # outlook = await self._generate_single_trade_outlook(
                    #     trade, context.portfolio_obj, stock_news_lookup, sector_lookup, fallback_sector_summary
                    # )
                    outlook = results.get(get_trade_key(trade), None)
                    trade.outlook = outlook
                except Exception as e:
                    logger.error(f"Failed to generate outlook for trade {trade.symbol}: {e}", exc_info=True)
                    trade.outlook = f"(Could not generate outlook: {str(e)})"
                    result.add_warning(f"Failed to generate outlook for {trade.symbol}")

        except Exception as e:
            result.add_error(f"Failed to generate trade outlooks: {str(e)}")

        return result

    def _build_stock_news_lookup(self, summarized_market_research: list[MarketResearchSummary]) -> Dict[str, Optional[str]]:
        """Build a lookup dictionary for stock news by symbol."""
        stock_news_lookup = {}
        if summarized_market_research.stock_news:
            stock_news_lookup = {
                k: v[0].data if v else None
                for k, v in summarized_market_research.stock_news.items()
            }
        return stock_news_lookup

    def _build_sector_lookup(self, summarized_market_research: list[MarketResearchSummary]) -> Tuple[Dict[str, str], Optional[str]]:
        """Build sector lookup and fallback summary."""
        sector_summaries = summarized_market_research.sector_analysis
        sector_lookup = {}

        for section in sector_summaries:
            if section.title:
                sector_lookup[section.title.lower()] = section.data

        fallback_sector_summary = sector_summaries[0].data if sector_summaries else None
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
        holding = portfolio_obj.holdings.get(symbol)
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
        trade_prompt = self.service._prompt_generator.generate_trade_outlook_prompt(
            trade=trade.model_dump(),
            news_summary=news_summary,
            sector_summary=sector_summary
        )

        # Get AI-generated outlook
        outlook = await self.service._gpt_client.generate_completion(
            prompt=trade_prompt,
            model=GPTModel.GPT_4O_MINI,
            temperature=0.6,
            use_cache=False
        )

        return outlook


class OverallTradeOutlookStage(DomainStage):
    """Generate an overall summary of trade performance."""

    async def execute(self, context: PulseContext) -> StageResult:
        result = StageResult()

        if not context.trade_analysis or not context.trade_stats:
            result.add_error("Missing trade analysis data for overall outlook generation")
            return result

        try:
            trade_outlook_prompt = self.service._prompt_generator.generate_trade_outlook_summary_prompt(
                trade_rows=[trade.model_dump() for trade in context.trade_analysis],
                trade_stats=context.trade_stats
            )

            context.trade_outlook = await self.service._gpt_client.generate_completion(
                prompt=trade_outlook_prompt,
                model=GPTModel.GPT_4_1_MINI,
                temperature=0.6,
                use_cache=False
            )

        except Exception as e:
            result.add_error(f"Failed to generate overall trade outlook: {str(e)}")

        return result


class PulseAnalysisStage(DomainStage):
    """Generate the main daily pulse analysis using AI."""

    async def execute(self, context: PulseContext) -> StageResult:
        result = StageResult()

        if not context.portfolio_obj or not context.summarized_market_research or not context.order_symbol_map:
            result.add_error("Missing required data for pulse analysis generation")
            return result

        try:
            # Compile prompt for GPT analysis
            pulse_prompt = await self.service._prompt_generator.compile_daily_pulse_prompt_with_symbols(
                context.portfolio_obj, context.summarized_market_research, context.order_symbol_map
            )
            context.prompts['pulse_prompt'] = pulse_prompt

            # Generate analysis using GPT
            context.pulse_analysis = await self.service._gpt_client.generate_completion(
                prompt=pulse_prompt,
                model=GPTModel.GPT_4_1,
                temperature=0.7,
                use_cache=False
            )

        except Exception as e:
            result.add_error(f"Failed to generate pulse analysis: {str(e)}")

        return result


class SendEmailsStage(DomainStage):
    """Send the daily pulse and debug emails."""

    async def execute(self, context: PulseContext) -> StageResult:
        result = StageResult()

        required_data = [
            context.pulse_analysis,
            context.portfolio_obj,
            context.summarized_market_research,
            context.trade_analysis,
            context.trade_outlook,
            context.raw_market_research
        ]

        if not all(required_data):
            result.add_error("Missing required data for email sending")
            return result

        try:
            # Generate and send main pulse email
            html_body = self.service._email_generator.generate_daily_pulse_html_email(
                analysis=context.pulse_analysis,
                portfolio_data=context.portfolio_obj,  # ✅ Changed parameter name
                market_research_summary=context.summarized_market_research,  # ✅ Changed parameter name and type
                trade_performance=[trade.model_dump() for trade in context.trade_analysis],
                trade_outlook=context.trade_outlook,
            )

            subject = self.service._email_generator.generate_daily_pulse_subject()
            await self.service._send_email_sendinblue(
                recipient=self.service.DEFAULT_EMAIL_RECIPIENT,
                subject=subject,
                html_body=html_body
            )

            # Send debug email
            await self._send_debug_email(context)

        except Exception as e:
            result.add_error(f"Failed to send emails: {str(e)}")

        return result

    async def _send_debug_email(self, context: PulseContext) -> None:
        """Send admin debug email with detailed information."""
        try:
            debug_report = DebugReport(
                portfolio_data=context.portfolio_obj,
                market_research=context.raw_market_research,
                prompts=context.prompts,
                gpt_analysis=context.pulse_analysis,
                sources={}
            )

            stats = {
                'search_count': context.search_count,
                'gpt_tokens': context.gpt_tokens,
                'total_execution_time_ms': context.total_execution_time
            }

            html_debug = self.service._email_generator.generate_admin_debug_html_report(debug_report, stats)
            await self.service._send_email_sendinblue(
                recipient=self.service.DEFAULT_EMAIL_RECIPIENT,
                subject='ADMIN DEBUG: Pulse Full Debug Info',
                html_body=html_debug
            )

            # Clean up stored prompts
            self.service._market_research_processor.clear_prompts()
            context.prompts = {}

        except Exception as e:
            logger.error(f"Failed to send admin debug report email: {e}", exc_info=True)


class CleanupStage(DomainStage):
    """Clean up resources and perform final tasks."""

    async def execute(self, context: PulseContext) -> StageResult:
        result = StageResult()

        try:
            # Update context with final metrics
            context.gpt_tokens = getattr(self.service._gpt_client, 'count', 0)
            context.search_count = getattr(self.service, 'search_count', 0)

            logger.info(f'Pipeline completed - Total execution time: {context.total_execution_time:.2f}ms')

        except Exception as e:
            result.add_warning(f"Cleanup issues: {str(e)}")

        return result


class PipelineExecutor:
    """Executes a pipeline of stages with error handling and retry logic."""

    def __init__(self):
        self.logger = get_logger(__name__)

    async def execute_pipeline(
        self,
        stages: List[PipelineStage],
        context: PulseContext
    ) -> PulseContext:
        """Execute a pipeline of stages sequentially."""
        self.logger.info(f"Starting pipeline execution with {len(stages)} stages")

        for stage in stages:
            # Check if we should fail fast
            if context.config.fail_fast and context.has_critical_errors:
                self.logger.error(f"Stopping pipeline due to critical errors before stage {stage.name}")
                break

            # Execute stage with retry logic
            result = await self._execute_stage_with_retry(stage, context)
            context.add_stage_result(stage.name, result)

            # Log stage completion
            status = "SUCCESS" if result.success else "FAILED"
            self.logger.info(f"Stage {stage.name} {status} - {result.execution_time_ms:.2f}ms")

            if result.errors:
                for error in result.errors:
                    self.logger.error(f"Stage {stage.name} error: {error}")

            if result.warnings:
                for warning in result.warnings:
                    self.logger.warning(f"Stage {stage.name} warning: {warning}")

        self.logger.info(f"Pipeline execution completed - Total time: {context.total_execution_time:.2f}ms")
        return context

    async def _execute_stage_with_retry(
        self,
        stage: PipelineStage,
        context: PulseContext
    ) -> StageResult:
        """Execute a stage with retry logic."""
        max_retries = context.config.retry_config.get(stage.name, 0)

        for attempt in range(max_retries + 1):
            if attempt > 0:
                self.logger.info(f"Retrying stage {stage.name} - attempt {attempt + 1}/{max_retries + 1}")

            result = await stage.run(context)

            # If successful or can't continue, return result
            if result.success or not result.can_continue:
                return result

            # If this was the last attempt, return the failed result
            if attempt == max_retries:
                return result

            # Wait before retry (simple exponential backoff)
            await asyncio.sleep(2 ** attempt)

        return result


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

        # Initialize Sendinblue email client
        self._setup_email_client(email_config)

        # Performance tracking
        self.search_count = 0
        self.gpt_tokens = 0

        # Initialize pipeline executor
        self._pipeline_executor = PipelineExecutor()

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

    def _create_pipeline_stages(self) -> List[PipelineStage]:
        """Create and return the list of pipeline stages."""
        return [
            InitializationStage("initialization", self),
            FetchPortfolioStage("fetch_portfolio", self),
            CaptureBalanceStage("capture_balance", self),
            FetchMarketResearchStage("fetch_market_research", self),
            SummarizeMarketResearchStage("summarize_market_research", self),
            EnrichOrdersStage("enrich_orders", self),
            TradePerformanceStage("trade_performance", self),
            TradeOutlooksStage("trade_outlooks", self),
            OverallTradeOutlookStage("overall_trade_outlook", self),
            PulseAnalysisStage("pulse_analysis", self),
            SendEmailsStage("send_emails", self),
            CleanupStage("cleanup", self),
        ]

    async def generate_daily_pulse(self, config: Optional[PipelineConfig] = None) -> Dict[str, Any]:
        """
        Generate a comprehensive daily pulse report for Robinhood account using pipeline pattern.

        Returns dict with success status and generated data.
        """
        logger.info('Starting daily pulse report generation with pipeline pattern')

        try:
            # Initialize context and configuration
            if config is None:
                config = PipelineConfig()

            context = PulseContext(config=config)

            # Create and execute pipeline
            stages = self._create_pipeline_stages()
            context = await self._pipeline_executor.execute_pipeline(stages, context)

            # Check for critical failures
            if context.has_critical_errors:
                error_messages = []
                for stage_name, result in context.stage_results.items():
                    if not result.can_continue:
                        error_messages.extend(result.errors)

                return {
                    'success': False,
                    'error': f"Pipeline failed with critical errors: {'; '.join(error_messages)}",
                    'stage_results': {name: result.model_dump() for name, result in context.stage_results.items()}
                }

            logger.info('Daily pulse report generated successfully via pipeline')

            return {
                'success': True,
                'data': {
                    'analysis': context.pulse_analysis,
                    'portfolio_summary': context.portfolio_obj.model_dump() if context.portfolio_obj else None,
                    'generated_at': DateTimeUtil.get_iso_date(),
                    'market_research': context.summarized_market_research.model_dump() if context.summarized_market_research else None,
                    'execution_metrics': {
                        'total_time_ms': context.total_execution_time,
                        'gpt_tokens': context.gpt_tokens,
                        'search_count': context.search_count,
                        'stages_executed': len(context.stage_results),
                        'stage_results': {name: result.model_dump() for name, result in context.stage_results.items()}
                    }
                }
            }

        except Exception as e:
            logger.error(f"Failed to generate daily pulse via pipeline: {e}", exc_info=True)
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
