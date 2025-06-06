from typing import Dict, List, Optional, Any, Set, Tuple
import uuid
import httpx
from pydantic import BaseModel, Field
from abc import ABC, abstractmethod
import asyncio
import time
import json
from datetime import datetime, timedelta
from clients.google_search_client import GoogleSearchClient
from clients.gpt_client import GPTClient
from framework.logger import get_logger
from domain.gpt import GPTModel
from models.robinhood_models import Article, Holding, MarketResearch, RobinhoodConfig, SectionTitle, SummarySection, MarketResearchSummary
from framework.configuration import Configuration
import feedparser
from framework.clients.cache_client import CacheClientAsync
from bs4 import BeautifulSoup

from services.robinhood.prompt_generator import PromptGenerator

logger = get_logger(__name__)

DEFAULT_RSS_FEEDS = []
MAX_ARTICLE_CHUNK_SIZE = 10000


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


class ResearchPipelineStage(ABC):
    """Abstract base class for research pipeline stages."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        """Execute the stage logic."""
        pass

    async def run(self, context: ResearchContext) -> ResearchStageResult:
        """Run the stage with timing and error handling."""
        if context.should_skip_stage(self.name):
            result = ResearchStageResult(success=True)
            result.warnings.append(f"Stage {self.name} was skipped")
            return result

        start_time = time.time()
        try:
            result = await self.execute(context)
            result.execution_time_ms = (time.time() - start_time) * 1000
            context.stage_results[self.name] = result
            return result
        except Exception as e:
            logger.error(f"Research stage {self.name} failed: {e}", exc_info=True)
            result = ResearchStageResult()
            result.add_error(f"Stage {self.name} failed: {str(e)}")
            result.execution_time_ms = (time.time() - start_time) * 1000
            context.stage_results[self.name] = result
            return result


class ResearchDomainStage(ResearchPipelineStage):
    """Base class for domain-specific research stages."""

    def __init__(self, name: str, processor: 'MarketResearchProcessor'):
        super().__init__(name)
        self.processor = processor


# === FETCH STAGES ===

class FetchRssArticlesStage(ResearchDomainStage):
    """Fetch articles from RSS feeds."""

    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        result = ResearchStageResult()

        mapping = await self.processor._fetch_rss_articles_content(urls=self.processor._rss_feeds or DEFAULT_RSS_FEEDS)

        try:
            rss_feeds = self.processor._rss_feeds or DEFAULT_RSS_FEEDS
            rss_articles = []

            for url in rss_feeds:
                logger.info(f'Processing RSS feed: {url}')
                content = mapping.get(url)
                feed = feedparser.parse(content)

                for idx, entry in enumerate(feed.entries[:context.config.rss_content_fetch_limit]):
                    if self.processor._is_excluded(entry.get('link', '')):
                        result.items_skipped += 1
                        continue

                    # Clean HTML from summary/snippet
                    raw_snippet = entry.get('summary', '')
                    snippet = BeautifulSoup(raw_snippet, 'lxml').get_text(separator=' ', strip=True) if raw_snippet else ''

                    article = Article(
                        title=entry.get('title', ''),
                        snippet=snippet,
                        link=entry.get('link', ''),
                        source=feed.feed.get('title', ''),
                        content=None
                    )

                    # Fetch content for limited number of articles
                    if article.link and idx < context.config.rss_content_fetch_limit:
                        try:
                            content = await self.processor._google_search_client.fetch_article_content(article.link)
                            if content:
                                article.content = BeautifulSoup(content, 'lxml').get_text(separator=' ', strip=True)
                        except Exception as e:
                            result.add_warning(f"Failed to fetch content for {article.link}: {str(e)}")

                    rss_articles.append(article)
                    result.items_processed += 1

            context.rss_articles = rss_articles
            logger.info(f"Fetched {len(rss_articles)} RSS articles")

        except Exception as e:
            result.add_error(f"Failed to fetch RSS articles: {str(e)}")

        return result


class FetchMarketConditionsStage(ResearchDomainStage):
    """Fetch market conditions data."""

    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        result = ResearchStageResult()

        try:
            market_conditions = await self.processor._google_search_client.search_market_conditions(
                exclude_sites=self.processor._exclude_sites,
                max_results=self.processor._market_condition_max_results
            )

            filtered = [a for a in (market_conditions or []) if not self.processor._is_excluded(a.link)]
            articles = [
                Article(title=a.title, snippet=a.snippet, link=a.link, source=a.source, content=None)
                for a in filtered
            ]

            # Enrich with content
            for article in articles:
                if article.link:
                    try:
                        content = await self.processor._google_search_client.fetch_article_content(article.link)
                        article.content = content if content else None
                        result.items_processed += 1
                    except Exception as e:
                        result.add_warning(f"Failed to fetch content for {article.link}: {str(e)}")

            context.market_conditions = articles
            logger.info(f"Fetched {len(articles)} market condition articles")

        except Exception as e:
            result.add_error(f"Failed to fetch market conditions: {str(e)}")

        return result


class FetchStockNewsStage(ResearchDomainStage):
    """Fetch stock-specific news."""

    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        result = ResearchStageResult()

        try:
            holdings = context.portfolio_data.get('holdings', {})
            stock_news = {}

            for symbol in holdings.keys():
                try:
                    news = await self.processor._google_search_client.search_finance_news(
                        symbol,
                        exclude_sites=self.processor._exclude_sites,
                        max_results=self.processor._max_results
                    )

                    filtered = [a for a in (news or []) if not self.processor._is_excluded(a.link)]
                    articles = [
                        Article(title=a.title, snippet=a.snippet, link=a.link, source=a.source, content=None)
                        for a in filtered
                    ]

                    # Enrich with content
                    for article in articles:
                        if article.link:
                            try:
                                content = await self.processor._google_search_client.fetch_article_content(article.link)
                                article.content = content if content else None
                            except Exception as e:
                                result.add_warning(f"Failed to fetch content for {article.link}: {str(e)}")

                    if articles:
                        stock_news[symbol] = articles
                        result.items_processed += len(articles)
                        logger.info(f'Found {len(articles)} news articles for {symbol}')

                except Exception as e:
                    result.add_warning(f"Failed to fetch news for {symbol}: {str(e)}")

            context.stock_news = stock_news

        except Exception as e:
            result.add_error(f"Failed to fetch stock news: {str(e)}")

        return result


class FetchSectorAnalysisStage(ResearchDomainStage):
    """Fetch sector analysis data."""

    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        result = ResearchStageResult()

        try:
            major_sectors = ['technology', 'healthcare', 'finance', 'energy']
            sector_analysis = []

            for sector in major_sectors:
                try:
                    analysis = await self.processor._google_search_client.search_sector_analysis(
                        sector,
                        exclude_sites=self.processor._exclude_sites,
                        max_results=self.processor._max_results
                    )

                    filtered = [a for a in (analysis or []) if not self.processor._is_excluded(a.link)]
                    articles = [
                        Article(title=a.title, snippet=a.snippet, link=a.link, source=a.source, content=None, sector=a.sector)
                        for a in filtered
                    ]

                    # Enrich with content
                    for article in articles:
                        if article.link:
                            try:
                                content = await self.processor._google_search_client.fetch_article_content(article.link)
                                article.content = content if content else None
                            except Exception as e:
                                result.add_warning(f"Failed to fetch content for {article.link}: {str(e)}")

                    if articles:
                        sector_analysis.extend(articles)
                        result.items_processed += len(articles)
                        logger.info(f'Found {len(articles)} {sector} sector articles')

                except Exception as e:
                    result.add_warning(f"Failed to fetch {sector} sector analysis: {str(e)}")

            context.sector_analysis = sector_analysis

        except Exception as e:
            result.add_error(f"Failed to fetch sector analysis: {str(e)}")

        return result


class FetchTruthSocialStage(ResearchDomainStage):
    """Fetch Truth Social posts from RSS feed."""

    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        result = ResearchStageResult()

        if not context.config.truth_social_enabled:
            result.add_warning("Truth Social analysis disabled in configuration")
            return result

        try:
            # Calculate date range for filtering
            end_date = datetime.now()
            start_date = end_date - timedelta(days=context.config.truth_social_days_lookback)

            logger.info(f"Fetching Truth Social posts from {context.config.truth_social_rss_url}")

            # Parse RSS feed
            feed = feedparser.parse(context.config.truth_social_rss_url)
            posts_dict = {}

            for entry in feed.entries:
                try:
                    # Parse published date
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        published_date = datetime(*entry.published_parsed[:6])
                    elif hasattr(entry, 'published'):
                        # Try to parse published string
                        try:
                            from dateutil import parser
                            published_date = parser.parse(entry.published)
                        except ImportError:
                            # Fallback to datetime parsing if dateutil not available
                            import time
                            published_date = datetime(*time.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %z')[:6])
                        except Exception:
                            logger.warning(f"Could not parse published date: {entry.published}")
                            continue
                    else:
                        logger.warning(f"No published date found for entry: {entry.get('title', 'Unknown')}")
                        continue

                    # Filter by date range
                    if published_date < start_date:
                        continue

                    # Clean content from HTML
                    content = entry.get('title', '') or entry.get('description', '')
                    if content:
                        content = BeautifulSoup(content, 'lxml').get_text(separator=' ', strip=True)

                    # Create post object
                    post = TruthSocialPost(
                        title=entry.get('title', ''),
                        content=content,
                        published_date=published_date,
                        link=entry.get('link', ''),
                        post_id=entry.get('id', '') or entry.get('guid', '') or str(hash(content))
                    )

                    posts_dict[post.get_key()] = post
                    result.items_processed += 1

                except Exception as e:
                    logger.warning(f"Failed to process Truth Social entry: {e}")
                    result.items_skipped += 1

            context.truth_social_posts = posts_dict
            logger.info(f"Fetched {len(posts_dict)} Truth Social posts from last {context.config.truth_social_days_lookback} days")

        except Exception as e:
            result.add_error(f"Failed to fetch Truth Social posts: {str(e)}")

        return result


class AnalyzeTruthSocialSignificanceStage(ResearchDomainStage):
    """Analyze Truth Social posts for market impact and trend significance."""

    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        result = ResearchStageResult()

        if not context.truth_social_posts:
            result.add_warning("No Truth Social posts to analyze")
            return result

        try:
            market_relevant_posts = []
            trend_significant_posts = []
            analysis_errors = []

            logger.info(f"Analyzing {len(context.truth_social_posts)} Truth Social posts for significance")

            sem = asyncio.Semaphore(10)  # Limit concurrent analyses
            results = {}

            async def _analyze_single_post(post: TruthSocialPost):
                async with sem:
                    logger.info(f"Analyzing post {post.post_id} from {post.published_date}")
                    results[post.post_id] = await self._analyze_single_post(post)

            tasks = []
            for post_key, post in context.truth_social_posts.items():
                tasks.append(_analyze_single_post(post))

            await asyncio.gather(*tasks)

            for post_key, post in context.truth_social_posts.items():
                try:
                    # Analyze individual post
                    # analysis = await self._analyze_single_post(post)
                    analysis = results.get(post.post_id)

                    # Create analyzed post object
                    analyzed_post = AnalyzedPost(
                        original_post=post,
                        market_impact=analysis.get('market_impact', False),
                        market_analysis=analysis.get('market_analysis'),
                        trend_significance=analysis.get('trend_significance', False),
                        trend_analysis=analysis.get('trend_analysis')
                    )

                    # Categorize the post
                    if analyzed_post.market_impact:
                        market_relevant_posts.append(analyzed_post)

                    if analyzed_post.trend_significance:
                        trend_significant_posts.append(analyzed_post)

                    result.items_processed += 1

                except Exception as e:
                    logger.error(f"Failed to analyze post {post_key}: {e}")
                    analysis_errors.append(f"Analysis failed for post {post_key}: {str(e)}")
                    result.items_skipped += 1

            # Create insights object
            date_range = f"Last {context.config.truth_social_days_lookback} days"
            insights = TruthSocialInsights(
                market_relevant_posts=market_relevant_posts,
                trend_significant_posts=trend_significant_posts,
                all_posts_analyzed=context.truth_social_posts,
                total_posts_analyzed=len(context.truth_social_posts),
                date_range=date_range,
                analysis_errors=analysis_errors
            )

            context.truth_social_insights = insights

            logger.info(f"Truth Social analysis complete: {len(market_relevant_posts)} market-relevant, "
                        f"{len(trend_significant_posts)} trend-significant posts")

        except Exception as e:
            result.add_error(f"Failed to analyze Truth Social posts: {str(e)}")

        return result

    async def _analyze_single_post(self, post: TruthSocialPost) -> Dict[str, Any]:
        """Analyze a single post for market impact and trend significance."""
        prompt = f"""
You are a financial analyst. Analyze this presidential post for significance.

Post Date: {post.published_date.strftime('%Y-%m-%d')}
Post Content: "{post.content}"

Determine:
1. Market Impact (true/false): Does this have direct market/economic implications?
2. If Market Impact = true: Provide 2-3 sentence analysis of market implications
3. Trend Significance (true/false): Does this represent an important policy/messaging trend?
4. If Trend Significance = true: Provide 2-3 sentence analysis of the trend

Respond ONLY in valid JSON format (without ```json or ```):
{{
    "market_impact": true/false,
    "market_analysis": "analysis if market_impact is true, otherwise null",
    "trend_significance": true/false, 
    "trend_analysis": "analysis if trend_significance is true, otherwise null"
}}
"""

        try:
            response = await self.processor._gpt_client.generate_completion(
                prompt=prompt,
                model=GPTModel.GPT_4O_MINI,
                temperature=0.2,
                use_cache=True
            )

            # Parse JSON response
            response = response.replace(r'```json', '').replace(r'```', '').strip()
            analysis = json.loads(response.strip())

            # Validate required fields
            if 'market_impact' not in analysis or 'trend_significance' not in analysis:
                raise ValueError("Missing required fields in analysis response")

            return analysis

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response for post analysis: {e}")
            logger.error(f"Raw response: {response}")
            return {
                "market_impact": False,
                "market_analysis": None,
                "trend_significance": False,
                "trend_analysis": None
            }
        except Exception as e:
            logger.error(f"Failed to analyze post: {e}")
            return {
                "market_impact": False,
                "market_analysis": None,
                "trend_significance": False,
                "trend_analysis": None
            }


# === PARALLEL FETCH STAGE ===

class ParallelFetchStage(ResearchDomainStage):
    """Fetch all data types in parallel for better performance."""

    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        result = ResearchStageResult()

        if not context.config.parallel_fetch:
            result.add_warning("Parallel fetch disabled, skipping")
            return result

        try:
            # Create fetch tasks
            fetch_tasks = [
                FetchTruthSocialStage("fetch_truth_social", self.processor).run(context),
                FetchRssArticlesStage("fetch_rss", self.processor).run(context),
                FetchMarketConditionsStage("fetch_market_conditions", self.processor).run(context),
                FetchStockNewsStage("fetch_stock_news", self.processor).run(context),
                FetchSectorAnalysisStage("fetch_sector_analysis", self.processor).run(context),
            ]

            # Execute in parallel
            stage_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            # Aggregate results
            for i, stage_result in enumerate(stage_results):
                if isinstance(stage_result, Exception):
                    result.add_error(f"Parallel fetch task {i} failed: {str(stage_result)}")
                elif isinstance(stage_result, ResearchStageResult):
                    result.items_processed += stage_result.items_processed
                    result.items_skipped += stage_result.items_skipped
                    result.errors.extend(stage_result.errors)
                    result.warnings.extend(stage_result.warnings)
                    if not stage_result.success:
                        result.success = False

            logger.info(f"Parallel fetch completed - processed {result.items_processed} items")

        except Exception as e:
            result.add_error(f"Parallel fetch coordination failed: {str(e)}")

        return result


# === FILTER STAGES ===

class FilterValueableArticlesStage(ResearchDomainStage):
    """Filter valuable articles using AI classification."""

    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        result = ResearchStageResult()

        try:
            # Filter RSS articles
            if context.rss_articles:
                valuable_rss, skipped_rss = await self._filter_articles(context.rss_articles, "RSS news")
                context.valuable_rss_articles = valuable_rss
                result.items_processed += len(valuable_rss)
                result.items_skipped += len(skipped_rss)

            # Filter stock news
            for symbol, articles in context.stock_news.items():
                valuable_articles, skipped_articles = await self._filter_articles(articles, f"{symbol} news")
                context.valuable_stock_news[symbol] = valuable_articles
                result.items_processed += len(valuable_articles)
                result.items_skipped += len(skipped_articles)

            # Filter sector analysis
            if context.sector_analysis:
                valuable_sector, skipped_sector = await self._filter_articles(context.sector_analysis, "sector analysis")
                context.valuable_sector_articles = valuable_sector
                result.items_processed += len(valuable_sector)
                result.items_skipped += len(skipped_sector)

        except Exception as e:
            result.add_error(f"Failed to filter articles: {str(e)}")

        return result

    async def _filter_articles(self, articles: List[Article], type_label: str) -> Tuple[List[Article], List[Article]]:
        """Filter articles using AI classification."""
        valuable_articles = []
        skipped_articles = []

        for article in articles:
            if article.content:
                valuable_articles.append(article)
            else:
                snippet = article.snippet or article.title
                prompt = f"""
You are an expert financial news analyst. Strictly classify short {type_label} snippets as either 'valuable' (contains specific, actionable, or newsworthy information for investors) or 'junk' (generic, marketing, navigation, or not useful for investment decisions).

Examples:
Junk: "Get the latest Visa Inc. (V) stock news and headlines to help you in your trading and investing decisions."
Junk: "Fitch Ratings is a leading provider of credit ratings, commentary and research for global capital markets."
Valuable: "Visa Inc. shares rose 2% after the company reported better-than-expected quarterly earnings and raised its full-year outlook."
Valuable: "23andMe will hold a second auction for its data assets as part of a restructuring plan."

Now classify this snippet:
Snippet: {snippet}

Respond with only one word: 'valuable' or 'junk'.
"""
                try:
                    result = await self.processor._gpt_client.generate_completion(
                        prompt=prompt,
                        model=GPTModel.GPT_3_5_TURBO,
                        temperature=0.0,
                        use_cache=True
                    )

                    if result.strip().lower() == 'valuable':
                        valuable_articles.append(article)
                    else:
                        skipped_articles.append(article)

                except Exception as e:
                    logger.error(f"AI classification failed for article: {e}")
                    skipped_articles.append(article)

        return valuable_articles, skipped_articles


# === PORTFOLIO AND TRADING STAGES ===

class CreatePortfolioSummaryStage(ResearchDomainStage):
    """Create portfolio holdings summary with structured data."""

    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        result = ResearchStageResult()

        try:
            holdings = context.portfolio_data.get('holdings', {})
            if not holdings:
                context.portfolio_summary_data = None
                context.portfolio_summary = None
                return result

            # Create structured portfolio data
            portfolio_rows = []
            total_value = 0

            parsed: dict[str, Holding] = {}
            for symbol, data in holdings.items():
                parsed[symbol] = Holding.model_validate(data)

            for symbol, holding in parsed.items():
                shares = float(holding.quantity)
                current_price = float(holding.price)
                market_value = shares * current_price
                avg_buy_price = float(getattr(holding, "average_buy_price", 0))
                cost_basis = avg_buy_price * shares if avg_buy_price else 0
                unrealized_pnl = market_value - cost_basis
                pnl_percent = (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0

                portfolio_rows.append({
                    'symbol': symbol,
                    'shares': shares,
                    'current_price': current_price,
                    'market_value': market_value,
                    'cost_basis': cost_basis,
                    'unrealized_pnl': unrealized_pnl,
                    'pnl_percent': pnl_percent
                })
                total_value += market_value

            # Store structured data for HTML table generation
            context.portfolio_summary_data = {
                'holdings': portfolio_rows,
                'total_value': total_value
            }

            # Store structured data as the summary (not text)
            context.portfolio_summary = context.portfolio_summary_data
            result.items_processed = len(holdings)

        except Exception as e:
            result.add_error(f"Failed to create portfolio summary: {str(e)}")
            context.portfolio_summary_data = None
            context.portfolio_summary = None

        return result


class CreateTradingSummaryStage(ResearchDomainStage):
    """Create trading summary with structured data."""

    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        result = ResearchStageResult()

        try:
            trading_data = context.portfolio_data.get('trading_activity', {})
            performance_data = context.portfolio_data.get('performance_metrics', {})

            # Structure recent trades data
            recent_trades = trading_data.get('recent_trades', [])
            trades_data = []

            for trade in recent_trades[-10:]:  # Last 10 trades
                trades_data.append({
                    'date': trade.get('date', 'N/A'),
                    'action': trade.get('action', 'N/A'),
                    'symbol': trade.get('symbol', 'N/A'),
                    'shares': trade.get('shares', 0),
                    'price': trade.get('price', 0),
                    'value': trade.get('shares', 0) * trade.get('price', 0)
                })

            # Structure performance metrics
            performance_metrics = {
                'total_return': performance_data.get('total_return', 0),
                'day_change': performance_data.get('day_change', 0),
                'week_change': performance_data.get('week_change', 0),
                'month_change': performance_data.get('month_change', 0)
            }

            # Store structured data for HTML generation
            context.trading_summary_data = {
                'recent_trades': trades_data,
                'performance_metrics': performance_metrics
            }

            # Store structured data as the summary (not text)
            context.trading_summary = context.trading_summary_data
            result.items_processed = len(recent_trades)

        except Exception as e:
            result.add_error(f"Failed to create trading summary: {str(e)}")
            context.trading_summary_data = None
            context.trading_summary = None

        return result


# === SUMMARIZATION STAGES ===

class SummarizeMarketConditionsStage(ResearchDomainStage):
    """Summarize market conditions and RSS articles."""

    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        result = ResearchStageResult()

        try:
            # Combine market conditions and RSS articles
            all_articles = context.valuable_rss_articles + context.market_conditions

            if not all_articles:
                context.market_conditions_summary = "No market conditions data available"
                return result

            summary = await self._summarize_article_chunks(all_articles, "market conditions", context.config.max_chunk_chars)
            context.market_conditions_summary = summary
            context.prompts['market_conditions'] = self._last_prompts
            result.items_processed = len(all_articles)

        except Exception as e:
            result.add_error(f"Failed to summarize market conditions: {str(e)}")

        return result

    async def _summarize_article_chunks(self, articles: List[Article], type_label: str, max_chunk_chars: int) -> str:
        """Summarize articles in chunks to handle token limits."""
        chunks = self._chunk_articles(articles, max_chunk_chars)
        chunk_summaries = []
        self._last_prompts = []

        tasks = []
        sem = asyncio.Semaphore(5)  # Limit concurrent summarization tasks

        async def summarize_chunk(prompt: str):
            async with sem:
                logger.info(f"Summarizing chunk with {len(prompt.splitlines())} lines")
                summary = await self.processor._gpt_client.generate_completion(
                    prompt=prompt,
                    model=GPTModel.GPT_4O_MINI)
                chunk_summaries.append(summary)

        for idx, chunk in enumerate(chunks):
            prompt_lines = [
                f"Summarize the following {type_label} articles in a concise, clear paragraph. "
                "Highlight key trends and sentiment. Ignore marketing/advertising content.\n"
            ]

            for i, article in enumerate(chunk, 1):
                prompt_lines.append(article.to_prompt_block(i))
                prompt_lines.append("")

            prompt = "\n".join(prompt_lines)
            self._last_prompts.append(prompt)

            tasks.append(summarize_chunk(prompt))

        await asyncio.gather(*tasks)

        if len(chunk_summaries) == 1:
            return chunk_summaries[0]
        else:
            # Merge multiple chunk summaries
            final_prompt = f"Summarize these {type_label} summaries into one concise paragraph:\n\n"
            for i, chunk_summary in enumerate(chunk_summaries, 1):
                final_prompt += f"Summary {i}: {chunk_summary}\n"

            self._last_prompts.append(final_prompt)
            return await self.processor._gpt_client.generate_completion(
                prompt=final_prompt,
                model=GPTModel.GPT_4O_MINI
            )

    def _chunk_articles(self, articles: List[Article], max_chunk_chars: int) -> List[List[Article]]:
        """Chunk articles to fit within token limits."""
        chunks = []
        current_chunk = []
        current_len = 0

        for article in articles:
            article_block = article.to_prompt_block() if hasattr(article, 'to_prompt_block') else str(article)
            block_len = len(article_block) + 1

            if current_len + block_len > max_chunk_chars and current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_len = 0

            current_chunk.append(article)
            current_len += block_len

        if current_chunk:
            chunks.append(current_chunk)

        return chunks


class SummarizeStockNewsStage(ResearchDomainStage):
    """Summarize stock-specific news for each symbol."""

    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        result = ResearchStageResult()

        try:
            context.prompts['stock_news'] = {}

            for symbol, articles in context.valuable_stock_news.items():
                if not articles:
                    continue

                try:
                    prompt_lines = [f"Summarize the following news for {symbol} in 2-3 sentences.\n"]
                    for i, article in enumerate(articles, 1):
                        prompt_lines.append(article.to_prompt_block(i))
                        prompt_lines.append("")

                    prompt = "\n".join(prompt_lines)
                    context.prompts['stock_news'][symbol] = prompt

                    summary = await self.processor._gpt_client.generate_completion(
                        prompt=prompt,
                        model=GPTModel.GPT_4O_MINI
                    )

                    context.stock_news_summaries[symbol] = summary
                    result.items_processed += len(articles)

                except Exception as e:
                    result.add_warning(f"Failed to summarize news for {symbol}: {str(e)}")
                    context.stock_news_summaries[symbol] = f"Failed to generate summary: {str(e)}"

        except Exception as e:
            result.add_error(f"Failed to summarize stock news: {str(e)}")

        return result


class SummarizeSectorAnalysisStage(ResearchDomainStage):
    """Summarize sector analysis articles."""

    async def execute(self, context: ResearchContext) -> ResearchStageResult:
        result = ResearchStageResult()

        try:
            if not context.valuable_sector_articles:
                context.sector_analysis_summary = "No valuable sector analysis available"
                return result

            prompt = self.processor._prompt_generator.generate_sector_analysis_summary_prompt(
                context.valuable_sector_articles
            )
            context.prompts['sector_analysis'] = prompt

            summary = await self.processor._gpt_client.generate_completion(
                prompt=prompt,
                model=GPTModel.GPT_4O_MINI
            )

            context.sector_analysis_summary = summary
            result.items_processed = len(context.valuable_sector_articles)

        except Exception as e:
            result.add_error(f"Failed to summarize sector analysis: {str(e)}")

        return result


# === PIPELINE EXECUTOR ===

class ResearchPipelineExecutor:
    """Executes research pipeline with error handling and retry logic."""

    def __init__(self):
        self.logger = get_logger(__name__)

    async def execute_pipeline(
        self,
        stages: List[ResearchPipelineStage],
        context: ResearchContext
    ) -> ResearchContext:
        """Execute a pipeline of research stages."""
        self.logger.info(f"Starting research pipeline with {len(stages)} stages")

        for stage in stages:
            if context.config.fail_fast and context.has_critical_errors:
                self.logger.error(f"Stopping research pipeline due to critical errors before stage {stage.name}")
                break

            result = await self._execute_stage_with_retry(stage, context)
            context.add_stage_result(stage.name, result)

            status = "SUCCESS" if result.success else "FAILED"
            self.logger.info(
                f"Research stage {stage.name} {status} - "
                f"{result.execution_time_ms:.2f}ms, "
                f"{result.items_processed} processed, "
                f"{result.items_skipped} skipped"
            )

            if result.errors:
                for error in result.errors:
                    self.logger.error(f"Research stage {stage.name} error: {error}")

            if result.warnings:
                for warning in result.warnings:
                    self.logger.warning(f"Research stage {stage.name} warning: {warning}")

        self.logger.info(f"Research pipeline completed - Total time: {context.total_execution_time:.2f}ms")
        return context

    async def _execute_stage_with_retry(
        self,
        stage: ResearchPipelineStage,
        context: ResearchContext
    ) -> ResearchStageResult:
        """Execute a stage with retry logic."""
        max_retries = context.config.retry_config.get(stage.name, 0)

        for attempt in range(max_retries + 1):
            if attempt > 0:
                self.logger.info(f"Retrying research stage {stage.name} - attempt {attempt + 1}/{max_retries + 1}")

            result = await stage.run(context)

            if result.success or not result.can_continue:
                return result

            if attempt == max_retries:
                return result

            await asyncio.sleep(2 ** attempt)

        return result


# === MAIN PROCESSOR ===

class MarketResearchProcessor:
    """Pipeline-based market research processor."""

    def __init__(
        self,
        configuration: Configuration,
        google_search_client: GoogleSearchClient,
        gpt_client: GPTClient,
        robinhood_config: RobinhoodConfig,
        prompt_generator: PromptGenerator,
        cache_client: CacheClientAsync
    ):
        self._google_search_client = google_search_client
        self._gpt_client = gpt_client
        self._robinhood_config = robinhood_config
        self._prompt_generator = prompt_generator
        self._cache_client = cache_client

        # Configuration
        daily_pulse_config = configuration.robinhood.get('daily_pulse', {})
        self._exclude_sites = daily_pulse_config.get('exclude_sites', [])
        self._rss_feeds = daily_pulse_config.get('rss_feeds', [])

        search_config = getattr(robinhood_config.daily_pulse, 'search', None) if hasattr(robinhood_config, 'daily_pulse') else None
        self._market_condition_max_results = getattr(search_config, 'market_condition_max_results', 10) if search_config else 10
        self._max_results = getattr(search_config, 'stock_news_max_results', 5) if search_config else 5

        # Pipeline executor
        self._pipeline_executor = ResearchPipelineExecutor()

        # Prompts storage
        self._prompts = {}

    def _is_excluded(self, url: str) -> bool:
        """Check if URL should be excluded."""
        if not url:
            return False
        return any(site in url for site in self._exclude_sites)

    def _create_pipeline_stages(self, use_parallel: bool = True) -> List[ResearchPipelineStage]:
        """Create pipeline stages for market research."""
        if use_parallel:
            return [
                ParallelFetchStage("parallel_fetch", self),
                AnalyzeTruthSocialSignificanceStage("analyze_truth_social", self),
                FilterValueableArticlesStage("filter_articles", self),
                CreatePortfolioSummaryStage("create_portfolio_summary", self),
                CreateTradingSummaryStage("create_trading_summary", self),
                SummarizeMarketConditionsStage("summarize_market_conditions", self),
                SummarizeStockNewsStage("summarize_stock_news", self),
                SummarizeSectorAnalysisStage("summarize_sector_analysis", self),
            ]
        else:
            return [
                FetchTruthSocialStage("fetch_truth_social", self),
                FetchRssArticlesStage("fetch_rss", self),
                FetchMarketConditionsStage("fetch_market_conditions", self),
                FetchStockNewsStage("fetch_stock_news", self),
                FetchSectorAnalysisStage("fetch_sector_analysis", self),
                AnalyzeTruthSocialSignificanceStage("analyze_truth_social", self),
                FilterValueableArticlesStage("filter_articles", self),
                CreatePortfolioSummaryStage("create_portfolio_summary", self),
                CreateTradingSummaryStage("create_trading_summary", self),
                SummarizeMarketConditionsStage("summarize_market_conditions", self),
                SummarizeStockNewsStage("summarize_stock_news", self),
                SummarizeSectorAnalysisStage("summarize_sector_analysis", self),
            ]

    async def get_market_research_data(self, portfolio_data: dict, config: RobinhoodConfig) -> MarketResearch:
        """Get raw market research data using pipeline."""
        logger.info('Gathering market research data via pipeline')

        try:
            # Initialize context
            config = ResearchPipelineConfig(
                parallel_fetch=True,
                rss_content_fetch_limit=config.daily_pulse.rss_content_fetch_limit
            )

            context = ResearchContext(config=config, portfolio_data=portfolio_data)

            # Create and execute fetch pipeline (including Truth Social analysis)
            fetch_stages = [
                ParallelFetchStage("parallel_fetch", self),
                AnalyzeTruthSocialSignificanceStage("analyze_truth_social", self)
            ]

            context = await self._pipeline_executor.execute_pipeline(fetch_stages, context)

            # Store pipeline metrics for parent pipeline to access
            self._last_pipeline_metrics = {
                'total_time_ms': context.total_execution_time,
                'stages_executed': len(context.stage_results),
                'items_processed': sum(r.items_processed for r in context.stage_results.values()),
                'items_skipped': sum(r.items_skipped for r in context.stage_results.values()),
                'stage_results': {name: result.model_dump() for name, result in context.stage_results.items()}
            }

            # Convert to legacy format (convert TruthSocialInsights to dict for Pydantic)
            research_data = {
                'market_conditions': context.rss_articles + context.market_conditions,
                'stock_news': context.stock_news,
                'sector_analysis': context.sector_analysis,
                'truth_social_insights': context.truth_social_insights.model_dump() if context.truth_social_insights else None,
                'search_errors': context.search_errors
            }

            logger.info('Market research data gathering completed')
            return MarketResearch.model_validate(research_data)

        except Exception as e:
            logger.error(f'Error gathering market research data: {str(e)}')
            return MarketResearch.model_validate({
                'market_conditions': [],
                'stock_news': {},
                'sector_analysis': [],
                'truth_social_insights': None,
                'search_errors': [f'Pipeline research gathering failed: {str(e)}']
            })

    async def summarize_market_research(self, market_research: MarketResearch, portfolio_data: dict = None) -> MarketResearchSummary:
        """Summarize market research data using pipeline."""
        logger.info('Summarizing market research data via pipeline')

        try:
            # Initialize context with existing data
            config = ResearchPipelineConfig()
            context = ResearchContext(config=config, portfolio_data=portfolio_data or {})

            # Convert from legacy format
            context.rss_articles = []
            context.market_conditions = market_research.market_conditions or []
            context.stock_news = market_research.stock_news or {}
            context.sector_analysis = market_research.sector_analysis or []
            context.truth_social_insights = market_research.truth_social_insights
            context.search_errors = market_research.search_errors or []

            # Create and execute summarization pipeline
            summary_stages = [
                FilterValueableArticlesStage("filter_articles", self),
                CreatePortfolioSummaryStage("create_portfolio_summary", self),
                CreateTradingSummaryStage("create_trading_summary", self),
                SummarizeMarketConditionsStage("summarize_market_conditions", self),
                SummarizeStockNewsStage("summarize_stock_news", self),
                SummarizeSectorAnalysisStage("summarize_sector_analysis", self),
            ]

            context = await self._pipeline_executor.execute_pipeline(summary_stages, context)

            # Store pipeline metrics for parent pipeline to access
            self._last_summary_metrics = {
                'total_time_ms': context.total_execution_time,
                'stages_executed': len(context.stage_results),
                'items_processed': sum(r.items_processed for r in context.stage_results.values()),
                'items_skipped': sum(r.items_skipped for r in context.stage_results.values()),
                'stage_results': {name: result.model_dump() for name, result in context.stage_results.items()}
            }

            # Store prompts for debugging
            self._prompts = context.prompts

            # Create summary sections using structured data
            portfolio_summary = []
            if context.portfolio_summary_data:
                portfolio_summary = [SummarySection(title=SectionTitle.PORTFOLIO_SUMMARY, snippet=context.portfolio_summary_data)]

            trading_summary = []
            if context.trading_summary_data:
                trading_summary = [SummarySection(title=SectionTitle.TRADING_SUMMARY_AND_PERFORMANCE, snippet=context.trading_summary_data)]

            # Convert to final summary format
            summary = {
                'market_conditions': [
                    SummarySection(title=SectionTitle.MARKET_CONDITIONS_SUMMARY, snippet=context.market_conditions_summary)
                ] if context.market_conditions_summary else [],
                'stock_news': {
                    symbol: [SummarySection(title=f'{symbol} News Summary', snippet=summary)]
                    for symbol, summary in context.stock_news_summaries.items()
                },
                'sector_analysis': [
                    SummarySection(title=SectionTitle.SECTOR_ANALYSIS, snippet=context.sector_analysis_summary)
                ] if context.sector_analysis_summary else [],
                'truth_social_summary': self._create_truth_social_summary_sections(context.truth_social_insights),
                'portfolio_summary': portfolio_summary,
                'trading_summary': trading_summary,
                'search_errors': context.search_errors,
                # Additional debugging info
                'market_conditions_skipped': [],  # Would need to track skipped articles
                'stock_news_skipped': {},
                'sector_analysis_skipped': []
            }

            logger.info('Market research summarization completed')
            return MarketResearchSummary.model_validate(summary)

        except Exception as e:
            logger.error(f'Error summarizing market research: {str(e)}')
            # Return minimal valid summary
            return MarketResearchSummary.model_validate({
                'market_conditions': [],
                'stock_news': {},
                'sector_analysis': [],
                'truth_social_summary': [],
                'portfolio_summary': [],
                'trading_summary': [],
                'search_errors': [f'Pipeline summarization failed: {str(e)}']
            })

    # def _create_truth_social_summary_sections(self, insights: Optional[Any]) -> List[SummarySection]:
    #     """Create summary sections for Truth Social insights."""
    #     if not insights:
    #         return []

    #     # Handle both dict (from database) and TruthSocialInsights object
    #     if isinstance(insights, dict):
    #         market_relevant_count = len(insights.get('market_relevant_posts', []))
    #         trend_significant_count = len(insights.get('trend_significant_posts', []))
    #         total_analyzed = insights.get('total_posts_analyzed', 0)
    #         date_range = insights.get('date_range', 'recent period')
    #     else:
    #         market_relevant_count = len(insights.market_relevant_posts)
    #         trend_significant_count = len(insights.trend_significant_posts)
    #         total_analyzed = insights.total_posts_analyzed
    #         date_range = insights.date_range

    #     sections = []

    #     # Market-relevant posts section
    #     if market_relevant_count > 0:
    #         market_content = f"Analysis of {market_relevant_count} market-relevant posts from {date_range}"
    #         sections.append(SummarySection(title='Presidential Market Insights', snippet=market_content))

    #     # Trend-significant posts section
    #     if trend_significant_count > 0:
    #         trend_content = f"Analysis of {trend_significant_count} trend-significant posts covering key policy themes"
    #         sections.append(SummarySection(title='Presidential Policy Trends', snippet=trend_content))

    #     # Summary section
    #     if market_relevant_count > 0 or trend_significant_count > 0:
    #         total_significant = market_relevant_count + trend_significant_count
    #         summary_content = f"Analyzed {total_analyzed} presidential posts from {date_range}. Found {total_significant} posts with market or policy significance."
    #         sections.append(SummarySection(title='Truth Social Analysis Summary', snippet=summary_content))

    #     return sections

    def _create_truth_social_summary_sections(self, insights: Optional[Any]) -> List[SummarySection]:
        """Create streamlined summary sections for Truth Social insights with HTML formatting."""
        if not insights:
            return []

        # Handle both dict (from database) and TruthSocialInsights object
        if isinstance(insights, dict):
            market_relevant_posts = insights.get('market_relevant_posts', [])
            trend_significant_posts = insights.get('trend_significant_posts', [])
            total_analyzed = insights.get('total_posts_analyzed', 0)
            date_range = insights.get('date_range', 'recent period')
            sentiment_analysis = insights.get('sentiment_analysis', {})
            market_impact_score = insights.get('market_impact_score', 0)
        else:
            market_relevant_posts = insights.market_relevant_posts
            trend_significant_posts = insights.trend_significant_posts
            total_analyzed = insights.total_posts_analyzed
            date_range = insights.date_range
            sentiment_analysis = getattr(insights, 'sentiment_analysis', {})
            market_impact_score = getattr(insights, 'market_impact_score', 0)

        sections = []

        # 1. Executive Summary
        if market_relevant_posts or trend_significant_posts:
            total_significant = len(market_relevant_posts) + len(trend_significant_posts)
            impact_level = "High" if market_impact_score > 7 else "Medium" if market_impact_score > 4 else "Low"

            # Get dominant sentiment
            dominant_sentiment = "Neutral"
            if sentiment_analysis and sentiment_analysis.get('scores'):
                sentiment_scores = sentiment_analysis['scores']
                dominant_sentiment = max(sentiment_scores.keys(), key=lambda k: sentiment_scores[k])

            executive_summary = f"""
            <div class="highlight">
                <h3><span class="icon-header">🏛️</span>Presidential Intelligence Brief</h3>
                
                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-label">Period</div>
                        <div class="metric-value">{date_range}</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">Posts Analyzed</div>
                        <div class="metric-value">{total_analyzed}</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">Market-Relevant</div>
                        <div class="metric-value">{len(market_relevant_posts)}</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">Impact Level</div>
                        <div class="metric-value">{impact_level} ({market_impact_score}/10)</div>
                    </div>
                </div>
                
                <div style="margin-top: 20px;">
                    <strong>Sentiment:</strong> <span class="{'positive' if dominant_sentiment.lower() == 'positive' else 'negative' if dominant_sentiment.lower() == 'negative' else ''}">{dominant_sentiment.title()}</span>
                </div>
                
                <div style="margin-top: 16px;">
                    <strong>Key Findings:</strong>
                    <ul style="margin: 8px 0; padding-left: 20px;">
                        <li>{total_significant} posts with market/policy implications identified</li>
                        <li>Primary focus: Economic policy, regulatory matters, trade relations</li>
                        <li>Market sentiment trending {dominant_sentiment.lower()} with potential volatility signals</li>
                    </ul>
                </div>
            </div>
            """

            sections.append(SummarySection(title=SectionTitle.PRESIDENTIAL_INTELLIGENCE_BRIEF, snippet=executive_summary))

        # 2. TOP IMPACT POSTS TABLE
        if market_relevant_posts or trend_significant_posts:
            top_posts_table = self._create_top_impact_posts_html_table(market_relevant_posts, trend_significant_posts)
            if top_posts_table:
                sections.append(SummarySection(title=SectionTitle.TOP_IMPACT_POSTS, snippet=top_posts_table))

        # 3. Market Impact & Policy Analysis (Combined)
        if market_relevant_posts:
            combined_analysis = self._analyze_market_and_policy_combined_html(market_relevant_posts, trend_significant_posts, sentiment_analysis)
            sections.append(SummarySection(title=SectionTitle.MARKET_IMPACT_POLICY_ANALYSIS, snippet=combined_analysis))

        # 4. Trading Strategy Implications
        if market_relevant_posts or trend_significant_posts:
            strategy_implications = self._generate_simplified_trading_implications_html(market_impact_score, sentiment_analysis)
            sections.append(SummarySection(title=SectionTitle.TRADING_STRATEGY_IMPLICATIONS, snippet=strategy_implications))

        return sections

    def _create_top_impact_posts_html_table(self, market_posts: List[Any], trend_posts: List[Any]) -> Optional[str]:
        """Create HTML table for top impact Truth Social posts."""
        try:
            # Combine and sort posts by impact score
            all_posts = []

            # Process market-relevant posts
            for post in market_posts:
                if isinstance(post, dict):
                    original_post = post.get('original_post', {})
                    market_impact_score = 8 if post.get('market_impact', False) else 0
                    analysis = post.get('market_analysis', '')
                else:
                    original_post = post.original_post
                    market_impact_score = 8 if post.market_impact else 0
                    analysis = post.market_analysis or ''

                all_posts.append({
                    'post': original_post,
                    'impact_score': market_impact_score,
                    'type': 'Market',
                    'analysis': analysis
                })

            # Process trend-significant posts
            for post in trend_posts:
                if isinstance(post, dict):
                    original_post = post.get('original_post', {})
                    trend_impact_score = 6 if post.get('trend_significance', False) else 0
                    analysis = post.get('trend_analysis', '')
                else:
                    original_post = post.original_post
                    trend_impact_score = 6 if post.trend_significance else 0
                    analysis = post.trend_analysis or ''

                # Only add if not already added as market post
                post_id = original_post.get('post_id') if isinstance(original_post, dict) else getattr(original_post, 'post_id', '')
                if not any(p['post'].get('post_id') == post_id or getattr(p['post'], 'post_id', '') == post_id for p in all_posts):
                    all_posts.append({
                        'post': original_post,
                        'impact_score': trend_impact_score,
                        'type': 'Policy',
                        'analysis': analysis
                    })

            # Sort by impact score and take top 10
            all_posts.sort(key=lambda x: x['impact_score'], reverse=True)
            top_posts = all_posts[:10]

            if not top_posts:
                return None

            # Create HTML table
            html = f"""
            <div class="pipeline-section">
                <table class="trade-performance-table">
                    <thead>
                        <tr>
                            <th style="width: 8%;">Rank</th>
                            <th style="width: 12%;">Date/Time</th>
                            <th style="width: 10%;">Type</th>
                            <th style="width: 8%;">Impact</th>
                            <th style="width: 40%;">Post Content</th>
                            <th style="width: 22%;">Analysis</th>
                        </tr>
                    </thead>
                    <tbody>
            """

            for i, post_data in enumerate(top_posts, 1):
                post = post_data['post']

                # Extract post data
                if isinstance(post, dict):
                    date = post.get('published_date', 'Unknown')
                    content = post.get('content', post.get('title', ''))
                    link = post.get('link', '')
                else:
                    date = getattr(post, 'published_date', 'Unknown')
                    content = getattr(post, 'content', '') or getattr(post, 'title', '')
                    link = getattr(post, 'link', '')

                # Format date
                if hasattr(date, 'strftime'):
                    formatted_date = date.strftime('%m/%d %H:%M')
                elif isinstance(date, str) and date != 'Unknown':
                    try:
                        from datetime import datetime
                        parsed_date = datetime.fromisoformat(date.replace('Z', '+00:00'))
                        formatted_date = parsed_date.strftime('%m/%d %H:%M')
                    except:
                        formatted_date = date
                else:
                    formatted_date = str(date)

                # Truncate content for table display
                # truncated_content = content[:150] + '...' if len(content) > 150 else content
                # truncated_content = ' '.join(truncated_content.split())  # Clean whitespace

                # Truncate analysis
                # analysis_text = post_data['analysis'][:100] + '...' if len(post_data['analysis']) > 100 else post_data['analysis']
                analysis_text = post_data['analysis']

                # Impact score styling
                impact_score = post_data['impact_score']
                impact_class = 'positive' if impact_score >= 7 else 'negative' if impact_score <= 3 else ''

                # Type badge styling
                # type_badge_style = 'background: #e8f5e8; color: #0d7833; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600;' if post_data[
                type_badge_style = 'color: #0d7833; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600;' if post_data[
                    'type'] == 'Market' else 'background: #fff3cd; color: #856404; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600;'

                html += f"""
                        <tr>
                            <td style="text-align: center; font-weight: 600;">{i}</td>
                            <td style="font-size: 13px;">{formatted_date}</td>
                            <td><span style="{type_badge_style}">{post_data['type']}</span></td>
                            <td style="text-align: center;"><span class="{impact_class}" style="font-weight: 600;">{impact_score}/10</span></td>
                            <td style="font-size: 13px; line-height: 1.4;">{content}</td>
                            <td style="font-size: 12px; color: #5f6368; line-height: 1.3;">{analysis_text}</td>
                        </tr>
                """

            html += """
                    </tbody>
                </table>
            </div>
            """

            return html

        except Exception as e:
            logger.error(f"Failed to create top impact posts HTML table: {e}")
            return None

    def _analyze_market_and_policy_combined_html(self, market_posts: List[Any], policy_posts: List[Any], sentiment_analysis: dict) -> str:
        """Combined analysis of market impact and policy trends in HTML format."""

        # Sentiment breakdown
        sentiment_html = ""
        if sentiment_analysis.get('scores'):
            scores = sentiment_analysis['scores']
            bullish_pct = int(scores.get('positive', 0) * 100)
            bearish_pct = int(scores.get('negative', 0) * 100)
            neutral_pct = int(scores.get('neutral', 0) * 100)

            sentiment_html = f"""
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-label">Bullish Sentiment</div>
                    <div class="metric-value positive">{bullish_pct}%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Bearish Sentiment</div>
                    <div class="metric-value negative">{bearish_pct}%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Neutral Sentiment</div>
                    <div class="metric-value">{neutral_pct}%</div>
                </div>
            </div>
            """

        # Get top 3 most impactful posts
        all_posts = market_posts + policy_posts
        top_posts_html = ""

        for i, post in enumerate(all_posts[:3]):
            if isinstance(post, dict):
                original_post = post.get('original_post', {})
                content = original_post.get('content', '')
                timestamp = original_post.get('published_date', 'Recent')
                impact_score = 8 if post.get('market_impact', False) else 6
                analysis = post.get('market_analysis') or post.get('trend_analysis', '')
            else:
                original_post = post.original_post
                content = getattr(original_post, 'content', '')
                timestamp = getattr(original_post, 'published_date', 'Recent')
                impact_score = 8 if post.market_impact else 6
                analysis = post.market_analysis or post.trend_analysis or ''

            # Format timestamp
            if hasattr(timestamp, 'strftime'):
                formatted_time = timestamp.strftime('%m/%d %H:%M')
            else:
                formatted_time = str(timestamp)

            impact_class = 'positive' if impact_score >= 7 else ''

            # <div style="background: #f8f9fa; border-left: 4px solid #2a5298; padding: 16px; margin-bottom: 12px; border-radius: 4px;">
            top_posts_html += f"""
            <div style="border-left: 4px solid #2a5298; padding: 16px; margin-bottom: 12px; border-radius: 4px;">
                <div style="font-weight: 600; color: #2a5298; margin-bottom: 8px;">
                    {formatted_time} • <span class="{impact_class}">Impact: {impact_score}/10</span>
                </div>
                <div style="font-style: italic; margin-bottom: 8px; line-height: 1.4;">
                    "{content}"
                </div>
                <div style="font-size: 13px; color: #5f6368;">
                    <strong>Analysis:</strong> {analysis}
                </div>
            </div>
            """

        analysis_html = f"""
        <div class="market-section">
            <h4 style="color: #2a5298; margin-top: 0;">Market-Moving Communications</h4>
            
            {sentiment_html}
            
            <h4 style="color: #2a5298; margin-top: 24px; margin-bottom: 16px;">Top Impact Posts</h4>
            {top_posts_html}
            
            <div style="background: #e8f0fe; padding: 16px; border-radius: 8px; margin-top: 20px;">
                <h4 style="color: #1e3c72; margin-top: 0;">Key Takeaways</h4>
                <ul style="margin: 0; padding-left: 20px; color: #2a5298;">
                    <li>Monitor affected sectors for volatility in next 24-48 hours</li>
                    <li>Watch for follow-up policy announcements or clarifications</li>
                    <li>Consider position adjustments based on sentiment shifts</li>
                </ul>
            </div>
        </div>
        """

        return analysis_html

    def _generate_simplified_trading_implications_html(self, impact_score: float, sentiment_analysis: dict) -> str:
        """Generate trading strategy implications in HTML format."""

        # Risk assessment
        if impact_score >= 7:
            risk_level = "HIGH RISK"
            risk_color = "#d73e2a"
            risk_icon = "🔴"
            risk_advice = "Reduce position sizes, consider hedging"
        elif impact_score >= 4:
            risk_level = "MEDIUM RISK"
            risk_color = "#f9ab00"
            risk_icon = "🟡"
            risk_advice = "Normal positions with enhanced monitoring"
        else:
            risk_level = "LOW RISK"
            risk_color = "#0d7833"
            risk_icon = "🟢"
            risk_advice = "Standard trading strategies viable"

        # Sentiment-based strategy
        strategy_note = ""
        if sentiment_analysis.get('scores'):
            sentiment_scores = sentiment_analysis['scores']
            dominant = max(sentiment_scores.keys(), key=lambda k: sentiment_scores[k])

            if dominant == 'positive':
                strategy_note = "Bullish sentiment supports growth stocks and risk-on assets"
            elif dominant == 'negative':
                strategy_note = "Bearish sentiment favors defensive positions and safe havens"
            else:
                strategy_note = "Neutral sentiment suggests range-bound trading opportunities"

        implications_html = f"""
        <div class="pipeline-section">
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-label">Risk Level</div>
                    <div class="metric-value" style="color: {risk_color};">{risk_icon} {risk_level}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Impact Score</div>
                    <div class="metric-value">{impact_score}/10</div>
                </div>
            </div>
            
            <div style="margin-top: 20px;">
                <h4 style="color: #2a5298; margin-bottom: 12px;">Strategy Guidance</h4>
                <div style="background: #f6f8fc; padding: 16px; border-radius: 8px; border-left: 4px solid {risk_color};">
                    <div style="font-weight: 600; margin-bottom: 8px;">{risk_advice}</div>
                    <div style="margin-bottom: 12px;">• {strategy_note}</div>
                    <div>• Plan for increased volatility in first hour post-announcement</div>
                    <div>• Tech/Energy/Healthcare sectors most likely to be affected</div>
                    <div>• Consider 50-75% normal position sizing during high-impact periods</div>
                </div>
            </div>
            
            <div style="margin-top: 20px;">
                <h4 style="color: #2a5298; margin-bottom: 12px;">Key Timing Windows</h4>
                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-label">Pre-Market</div>
                        <div class="metric-value" style="font-size: 16px;">4:00-9:30 AM EST</div>
                        <div style="font-size: 12px; color: #5f6368; margin-top: 4px;">Watch futures reaction</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">Market Open</div>
                        <div class="metric-value" style="font-size: 16px;">9:30-10:00 AM EST</div>
                        <div style="font-size: 12px; color: #5f6368; margin-top: 4px;">Highest volatility window</div>
                    </div>
                </div>
            </div>
        </div>
        """

        return implications_html

    def get_prompts(self) -> Dict[str, Any]:
        """Get stored prompts for debugging."""
        return self._prompts

    def clear_prompts(self) -> None:
        """Clear all stored prompts."""
        self._prompts = {}

    async def _fetch_rss_articles_content(self, urls: list[str]):
        async def fetch_content(url: str) -> str:
            async with httpx.AsyncClient() as client:
                cache_key = f'rss_content:{url}'
                cached_content = await self._cache_client.get_cache(cache_key)
                if cached_content:
                    return cached_content

                data = await client.get(url).text

                await self._cache_client.get_cache(cache_key, data, expire=60)  # Cache for 1 hour

                return {
                    url: data
                }

        tasks = [fetch_content(url) for url in urls]

        return await asyncio.gather(*tasks, return_exceptions=True)
