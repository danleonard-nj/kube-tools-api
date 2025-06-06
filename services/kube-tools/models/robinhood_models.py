from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any, Set, Union
from datetime import date, datetime

DEFAULT_RSS_FEEDS = []
MAX_ARTICLE_CHUNK_SIZE = 10000


class SectionTitle:
    """Enum-like class for section names."""
    MARKET_CONDITIONS = "Market Conditions"
    STOCK_NEWS = "Stock News"
    SECTOR_ANALYSIS = "Sector Analysis"
    TRUTH_SOCIAL = "Truth Social"
    PORTFOLIO_SUMMARY = "Portfolio Holdings"
    TRADING_SUMMARY = "Trading Summary & Performance"


class Holding(BaseModel):
    price: str
    quantity: str
    average_buy_price: str
    equity: Optional[str] = None
    percent_change: Optional[str] = None
    intraday_percent_change: Optional[str] = None
    equity_change: Optional[str] = None
    type: Optional[str] = None
    name: Optional[str] = None
    id: Optional[str] = None
    pe_ratio: Optional[str] = None
    percentage: Optional[str] = None


class Order(BaseModel):
    id: str
    symbol: Optional[str] = None
    ref_id: Optional[str] = None
    url: Optional[str] = None
    account: Optional[str] = None
    user_uuid: Optional[str] = None
    position: Optional[str] = None
    cancel: Optional[Any] = None
    instrument: Optional[Any] = None
    instrument_id: Optional[str] = None
    cumulative_quantity: Optional[str] = None
    average_price: Optional[str] = None
    fees: Optional[str] = None
    sec_fees: Optional[str] = None
    taf_fees: Optional[str] = None
    cat_fees: Optional[str] = None
    gst_fees: Optional[str] = None
    state: Optional[str] = None
    derived_state: Optional[str] = None
    pending_cancel_open_agent: Optional[Any] = None
    type: Optional[str] = None
    side: Optional[str] = None
    time_in_force: Optional[str] = None
    trigger: Optional[str] = None
    price: Optional[str] = None
    stop_price: Optional[str] = None
    quantity: Optional[str] = None
    reject_reason: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_transaction_at: Optional[str] = None
    executions: Optional[List[Any]] = None
    extended_hours: Optional[bool] = None
    market_hours: Optional[str] = None
    override_dtbp_checks: Optional[bool] = None
    override_day_trade_checks: Optional[bool] = None
    response_category: Optional[Any] = None
    stop_triggered_at: Optional[Any] = None
    last_trail_price: Optional[Any] = None
    last_trail_price_updated_at: Optional[Any] = None
    last_trail_price_source: Optional[Any] = None
    dollar_based_amount: Optional[dict] = None
    total_notional: Optional[dict] = None
    executed_notional: Optional[dict] = None
    investment_schedule_id: Optional[Any] = None
    is_ipo_access_order: Optional[bool] = None
    ipo_access_cancellation_reason: Optional[Any] = None
    ipo_access_lower_collared_price: Optional[Any] = None
    ipo_access_upper_collared_price: Optional[Any] = None
    ipo_access_upper_price: Optional[Any] = None
    ipo_access_lower_price: Optional[Any] = None
    is_ipo_access_price_finalized: Optional[bool] = None
    is_visible_to_user: Optional[bool] = None
    has_ipo_access_custom_price_limit: Optional[bool] = None
    is_primary_account: Optional[bool] = None
    order_form_version: Optional[int] = None
    preset_percent_limit: Optional[str] = None
    order_form_type: Optional[str] = None
    last_update_version: Optional[int] = None
    placed_agent: Optional[str] = None
    is_editable: Optional[bool] = None
    replaces: Optional[Any] = None
    user_cancel_request_state: Optional[str] = None
    tax_lot_selection_type: Optional[str] = None
    position_effect: Optional[str] = None


class PortfolioProfile(BaseModel):
    url: Optional[str] = None
    account: Optional[str] = None
    start_date: Optional[str] = None
    market_value: Optional[str] = None
    equity: Optional[str] = None
    extended_hours_market_value: Optional[str] = None
    extended_hours_equity: Optional[str] = None
    extended_hours_portfolio_equity: Optional[str] = None
    last_core_market_value: Optional[str] = None
    last_core_equity: Optional[str] = None
    last_core_portfolio_equity: Optional[str] = None
    excess_margin: Optional[str] = None
    excess_maintenance: Optional[str] = None
    excess_margin_with_uncleared_deposits: Optional[str] = None
    excess_maintenance_with_uncleared_deposits: Optional[str] = None
    equity_previous_close: Optional[str] = None
    portfolio_equity_previous_close: Optional[str] = None
    adjusted_equity_previous_close: Optional[str] = None
    adjusted_portfolio_equity_previous_close: Optional[str] = None
    withdrawable_amount: Optional[str] = None
    unwithdrawable_deposits: Optional[str] = None
    unwithdrawable_grants: Optional[str] = None
    is_primary_account: Optional[bool] = None


class AccountProfile(BaseModel):
    url: Optional[str] = None
    portfolio_cash: Optional[str] = None
    can_downgrade_to_cash: Optional[str] = None
    user: Optional[str] = None
    account_number: Optional[str] = None
    type: Optional[str] = None
    brokerage_account_type: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deactivated: Optional[bool] = None
    deposit_halted: Optional[bool] = None
    withdrawal_halted: Optional[bool] = None
    only_position_closing_trades: Optional[bool] = None
    buying_power: Optional[str] = None
    onbp: Optional[str] = None
    cash_available_for_withdrawal: Optional[str] = None
    cash_available_for_withdrawal_without_margin: Optional[str] = None
    cash: Optional[str] = None
    amount_eligible_for_deposit_cancellation: Optional[str] = None
    cash_held_for_orders: Optional[str] = None
    uncleared_deposits: Optional[str] = None
    sma: Optional[str] = None
    sma_held_for_orders: Optional[str] = None
    unsettled_funds: Optional[str] = None
    unsettled_debit: Optional[str] = None
    crypto_buying_power: Optional[str] = None
    max_ach_early_access_amount: Optional[str] = None
    cash_balances: Optional[Any] = None
    margin_balances: Optional[dict] = None
    sweep_enabled: Optional[bool] = None
    sweep_enrolled: Optional[bool] = None
    instant_eligibility: Optional[dict] = None
    option_level: Optional[str] = None
    is_pinnacle_account: Optional[bool] = None
    rhs_account_number: Optional[int] = None
    state: Optional[str] = None
    active_subscription_id: Optional[Any] = None
    locked: Optional[bool] = None
    permanently_deactivated: Optional[bool] = None
    ipo_access_restricted: Optional[bool] = None
    ipo_access_restricted_reason: Optional[Any] = None
    received_ach_debit_locked: Optional[bool] = None
    drip_enabled: Optional[bool] = None
    eligible_for_fractionals: Optional[bool] = None
    eligible_for_drip: Optional[bool] = None
    eligible_for_cash_management: Optional[bool] = None
    cash_management_enabled: Optional[bool] = None
    option_trading_on_expiration_enabled: Optional[bool] = None
    cash_held_for_options_collateral: Optional[str] = None
    fractional_position_closing_only: Optional[bool] = None
    user_id: Optional[str] = None
    equity_trading_lock: Optional[str] = None
    option_trading_lock: Optional[str] = None
    disable_adt: Optional[bool] = None
    management_type: Optional[str] = None
    dynamic_instant_limit: Optional[str] = None
    affiliate: Optional[str] = None
    second_trade_suitability_completed: Optional[bool] = None
    has_futures_account: Optional[bool] = None
    is_default: Optional[bool] = None
    car_valid_until: Optional[str] = None
    nickname: Optional[str] = None
    ref_id: Optional[str] = None


class PortfolioData(BaseModel):
    account_profile: AccountProfile
    portfolio_profile: PortfolioProfile
    holdings: Dict[str, Holding]
    positions: Any
    recent_orders: List[Order]
    watchlist: List[Any]
    historical_equity: Optional[List[Dict[str, Any]]] = None


class Article(BaseModel):
    title: str
    snippet: Optional[str] = None
    link: Optional[str] = None
    source: Optional[str] = None
    content: Optional[str] = None
    sector: Optional[str] = None

    def to_prompt_block(self, idx=None):
        lines = []
        prefix = f"{idx}. " if idx is not None else ""
        lines.append(f"{prefix}{self.title}")
        if self.snippet:
            lines.append(f"   {self.snippet}")
        if self.source:
            lines.append(f"   Source: {self.source}")
        if self.content:
            lines.append(f"   Content: {self.content}")
        return "\n".join(lines)

    @staticmethod
    def dict_to_prompt_block(article_dict, idx=None):
        lines = []
        prefix = f"{idx}. " if idx is not None else ""
        lines.append(f"{prefix}{article_dict.get('title', '')}")
        if article_dict.get('sector'):
            lines.append(f"   Sector: {article_dict.get('sector', '').title()}")
        if article_dict.get('snippet'):
            lines.append(f"   {article_dict.get('snippet', '')}")
        if article_dict.get('source'):
            lines.append(f"   Source: {article_dict.get('source', '')}")
        if article_dict.get('content'):
            lines.append(f"   Content: {article_dict.get('content', '')}")
        return "\n".join(lines)


class SummarySection(BaseModel):
    """Summary section that can contain either text or structured data."""
    title: str
    snippet: Union[str, Dict[str, Any]]  # Now supports both text and structured data

    class Config:
        # Allow arbitrary types for flexibility
        arbitrary_types_allowed = True


class TruthSocialPost(BaseModel):
    """Individual Truth Social post data."""
    title: str
    content: str
    published_date: datetime
    link: str
    post_id: str

    def get_key(self) -> str:
        """Generate unique key for this post."""
        return f"{self.published_date.strftime('%Y%m%d')}_{self.post_id}"


class AnalyzedPost(BaseModel):
    """Truth Social post with AI analysis attached."""
    original_post: TruthSocialPost
    market_impact: bool = False
    market_analysis: Optional[str] = None
    trend_significance: bool = False
    trend_analysis: Optional[str] = None
    analysis_timestamp: datetime = Field(default_factory=datetime.now)


class TruthSocialInsights(BaseModel):
    """Complete Truth Social analysis results."""
    market_relevant_posts: List[AnalyzedPost] = Field(default_factory=list)
    trend_significant_posts: List[AnalyzedPost] = Field(default_factory=list)
    all_posts_analyzed: Dict[str, TruthSocialPost] = Field(default_factory=dict)
    total_posts_analyzed: int = 0
    date_range: str = ""
    analysis_errors: List[str] = Field(default_factory=list)


class MarketResearchSummary(BaseModel):
    """Updated to include Truth Social summaries."""
    market_conditions: List[SummarySection] = Field(default_factory=list)
    stock_news: Dict[str, List[SummarySection]] = Field(default_factory=dict)
    sector_analysis: List[SummarySection] = Field(default_factory=list)
    truth_social_summary: List[SummarySection] = Field(default_factory=list)
    # ✅ ADD THESE TWO LINES:
    portfolio_summary: List[SummarySection] = Field(default_factory=list)
    trading_summary: List[SummarySection] = Field(default_factory=list)
    search_errors: List[str] = Field(default_factory=list)

    # Optional debugging fields (existing)
    market_conditions_skipped: List[str] = Field(default_factory=list)
    stock_news_skipped: Dict[str, List[str]] = Field(default_factory=dict)
    sector_analysis_skipped: List[str] = Field(default_factory=list)


class MarketResearch(BaseModel):
    """Updated to include Truth Social data."""
    market_conditions: List[Article] = Field(default_factory=list)
    stock_news: Dict[str, List[Article]] = Field(default_factory=dict)
    sector_analysis: List[Article] = Field(default_factory=list)
    truth_social_insights: Optional[TruthSocialInsights] = None  # NEW FIELD
    search_errors: List[str] = Field(default_factory=list)


class DebugReport(BaseModel):
    portfolio_data: PortfolioData
    market_research: MarketResearch
    prompts: Dict[str, Any]
    gpt_analysis: str
    sources: Dict[str, Any]


class DailyPulseSearchConfig(BaseModel):
    market_condition_max_results: int
    stock_news_max_results: int
    sector_analysis_max_results: int


class DailyPulseConfig(BaseModel):
    search: DailyPulseSearchConfig
    exclude_sites: List[str]
    rss_feeds: List[str]
    rss_content_fetch_limit: int = 5

    truth_social_enabled: bool = True
    truth_social_rss_url: str = "https://trumpstruth.org/feed"
    truth_social_days_lookback: int = 7


class RobinhoodConfig(BaseModel):
    username: str
    password: str
    daily_pulse: DailyPulseConfig


# === TRUTH SOCIAL DATA MODELS ===

class TruthSocialPost(BaseModel):
    """Individual Truth Social post data."""
    title: str
    content: str
    published_date: datetime
    link: str
    post_id: str

    def get_key(self) -> str:
        """Generate unique key for this post."""
        return f"{self.published_date.strftime('%Y%m%d')}_{self.post_id}"


class AnalyzedPost(BaseModel):
    """Truth Social post with AI analysis attached."""
    original_post: TruthSocialPost
    market_impact: bool = False
    market_analysis: Optional[str] = None
    trend_significance: bool = False
    trend_analysis: Optional[str] = None
    analysis_timestamp: datetime = Field(default_factory=datetime.now)


class TruthSocialInsights(BaseModel):
    """Complete Truth Social analysis results."""
    market_relevant_posts: List[AnalyzedPost] = Field(default_factory=list)
    trend_significant_posts: List[AnalyzedPost] = Field(default_factory=list)
    all_posts_analyzed: Dict[str, TruthSocialPost] = Field(default_factory=dict)
    total_posts_analyzed: int = 0
    date_range: str = ""
    analysis_errors: List[str] = Field(default_factory=list)


class ResearchStageResult(BaseModel):
    """Result of a research pipeline stage execution."""
    success: bool = True
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    can_continue: bool = True
    execution_time_ms: float = 0.0
    items_processed: int = 0
    items_skipped: int = 0

    def add_error(self, error: str, critical: bool = True) -> None:
        """Add an error to the result."""
        self.errors.append(error)
        self.success = False
        if critical:
            self.can_continue = False

    def add_warning(self, warning: str) -> None:
        """Add a warning to the result."""
        self.warnings.append(warning)


class ResearchPipelineConfig(BaseModel):
    """Configuration for research pipeline execution."""
    skip_stages: Set[str] = Field(default_factory=set)
    retry_config: Dict[str, int] = Field(default_factory=dict)
    fail_fast: bool = False
    max_chunk_chars: int = MAX_ARTICLE_CHUNK_SIZE
    rss_content_fetch_limit: int = 5
    parallel_fetch: bool = True  # Fetch different data types in parallel

    # Truth Social configuration
    truth_social_rss_url: str = "https://trumpstruth.org/feed"
    truth_social_days_lookback: int = 7
    truth_social_enabled: bool = True


class ResearchContext(BaseModel):
    """Context object that flows through research pipeline stages."""
    # Configuration
    config: ResearchPipelineConfig = Field(default_factory=ResearchPipelineConfig)
    portfolio_data: Dict[str, Any] = Field(default_factory=dict)

    # Raw fetched data
    rss_articles: List[Article] = Field(default_factory=list)
    market_conditions: List[Article] = Field(default_factory=list)
    stock_news: Dict[str, List[Article]] = Field(default_factory=dict)
    sector_analysis: List[Article] = Field(default_factory=list)
    truth_social_posts: Dict[str, TruthSocialPost] = Field(default_factory=dict)

    # Processed data
    valuable_rss_articles: List[Article] = Field(default_factory=list)
    valuable_stock_news: Dict[str, List[Article]] = Field(default_factory=dict)
    valuable_sector_articles: List[Article] = Field(default_factory=list)
    truth_social_insights: Optional[TruthSocialInsights] = None

    # Summaries - Now support both text (legacy) and structured data
    market_conditions_summary: str = ""
    stock_news_summaries: Dict[str, str] = Field(default_factory=dict)
    sector_analysis_summary: str = ""

    # NEW: Structured data fields
    portfolio_summary_data: Optional[Dict[str, Any]] = None
    trading_summary_data: Optional[Dict[str, Any]] = None

    # Legacy text fields (for backwards compatibility)
    portfolio_summary: str = ""
    trading_summary: str = ""

    # Metadata
    search_errors: List[str] = Field(default_factory=list)
    stage_results: Dict[str, ResearchStageResult] = Field(default_factory=dict)
    prompts: Dict[str, Any] = Field(default_factory=dict)

    @property
    def has_critical_errors(self) -> bool:
        """Check if any stage has critical errors."""
        return any(not result.can_continue for result in self.stage_results.values())

    @property
    def total_execution_time(self) -> float:
        """Total execution time across all stages."""
        return sum(result.execution_time_ms for result in self.stage_results.values())

    def add_stage_result(self, stage_name: str, result: ResearchStageResult) -> None:
        """Add a stage result to the context."""
        self.stage_results[stage_name] = result

    def should_skip_stage(self, stage_name: str) -> bool:
        """Check if a stage should be skipped."""
        return stage_name in self.config.skip_stages

    class Config:
        arbitrary_types_allowed = True
