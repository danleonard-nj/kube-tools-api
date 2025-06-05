from typing import Dict, List, Optional, Any, Set, Tuple
from pydantic import BaseModel, Field
from abc import ABC, abstractmethod
import asyncio
import time
from clients.google_search_client import GoogleSearchClient
from clients.gpt_client import GPTClient
from framework.logger import get_logger
from domain.gpt import GPTModel
from models.robinhood_models import Article, MarketResearch, RobinhoodConfig, SummarySection, MarketResearchSummary
from framework.configuration import Configuration
import feedparser
from bs4 import BeautifulSoup
from services.prompt_generator import PromptGenerator

logger = get_logger(__name__)

DEFAULT_RSS_FEEDS = []
MAX_ARTICLE_CHUNK_SIZE = 10000


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

    # Processed data
    valuable_rss_articles: List[Article] = Field(default_factory=list)
    valuable_stock_news: Dict[str, List[Article]] = Field(default_factory=dict)
    valuable_sector_articles: List[Article] = Field(default_factory=list)

    # Summaries
    market_conditions_summary: str = ""
    stock_news_summaries: Dict[str, str] = Field(default_factory=dict)
    sector_analysis_summary: str = ""

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
            return result
        except Exception as e:
            logger.error(f"Research stage {self.name} failed: {e}", exc_info=True)
            result = ResearchStageResult()
            result.add_error(f"Stage {self.name} failed: {str(e)}")
            result.execution_time_ms = (time.time() - start_time) * 1000
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

        try:
            rss_feeds = self.processor._rss_feeds or DEFAULT_RSS_FEEDS
            rss_articles = []

            for url in rss_feeds:
                logger.info(f'Processing RSS feed: {url}')
                feed = feedparser.parse(url)

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

            summary = await self._summarize_article_chunks(all_articles, "market conditions")
            context.market_conditions_summary = summary
            context.prompts['market_conditions'] = self._last_prompts
            result.items_processed = len(all_articles)

        except Exception as e:
            result.add_error(f"Failed to summarize market conditions: {str(e)}")

        return result

    async def _summarize_article_chunks(self, articles: List[Article], type_label: str) -> str:
        """Summarize articles in chunks to handle token limits."""
        chunks = self._chunk_articles(articles, context.config.max_chunk_chars)
        chunk_summaries = []
        self._last_prompts = []

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

            summary = await self.processor._gpt_client.generate_completion(
                prompt=prompt,
                model="gpt-4o-mini"
            )
            chunk_summaries.append(summary)

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
                model="gpt-4o-mini"
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
                        model="gpt-4o-mini"
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
                model="gpt-4o-mini"
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
        prompt_generator: PromptGenerator
    ):
        self._google_search_client = google_search_client
        self._gpt_client = gpt_client
        self._robinhood_config = robinhood_config
        self._prompt_generator = prompt_generator

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
                FilterValueableArticlesStage("filter_articles", self),
                SummarizeMarketConditionsStage("summarize_market_conditions", self),
                SummarizeStockNewsStage("summarize_stock_news", self),
                SummarizeSectorAnalysisStage("summarize_sector_analysis", self),
            ]
        else:
            return [
                FetchRssArticlesStage("fetch_rss", self),
                FetchMarketConditionsStage("fetch_market_conditions", self),
                FetchStockNewsStage("fetch_stock_news", self),
                FetchSectorAnalysisStage("fetch_sector_analysis", self),
                FilterValueableArticlesStage("filter_articles", self),
                SummarizeMarketConditionsStage("summarize_market_conditions", self),
                SummarizeStockNewsStage("summarize_stock_news", self),
                SummarizeSectorAnalysisStage("summarize_sector_analysis", self),
            ]

    async def get_market_research_data(self, portfolio_data: dict) -> MarketResearch:
        """Get raw market research data using pipeline."""
        logger.info('Gathering market research data via pipeline')

        try:
            # Initialize context
            config = ResearchPipelineConfig(parallel_fetch=True)
            context = ResearchContext(config=config, portfolio_data=portfolio_data)

            # Create and execute fetch pipeline (just fetching, no summarization)
            fetch_stages = [
                ParallelFetchStage("parallel_fetch", self)
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

            # Convert to legacy format
            research_data = {
                'market_conditions': context.rss_articles + context.market_conditions,
                'stock_news': context.stock_news,
                'sector_analysis': context.sector_analysis,
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
                'search_errors': [f'Pipeline research gathering failed: {str(e)}']
            })

    async def summarize_market_research(self, market_research: MarketResearch) -> MarketResearchSummary:
        """Summarize market research data using pipeline."""
        logger.info('Summarizing market research data via pipeline')

        try:
            # Initialize context with existing data
            config = ResearchPipelineConfig()
            context = ResearchContext(config=config)

            # Convert from legacy format
            context.rss_articles = []
            context.market_conditions = market_research.market_conditions or []
            context.stock_news = market_research.stock_news or {}
            context.sector_analysis = market_research.sector_analysis or []
            context.search_errors = market_research.search_errors or []

            # Create and execute summarization pipeline
            summary_stages = [
                FilterValueableArticlesStage("filter_articles", self),
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

            # Convert to legacy format
            summary = {
                'market_conditions': [
                    SummarySection(title='Market Conditions Summary', snippet=context.market_conditions_summary)
                ] if context.market_conditions_summary else [],
                'stock_news': {
                    symbol: [SummarySection(title=f'{symbol} News Summary', snippet=summary)]
                    for symbol, summary in context.stock_news_summaries.items()
                },
                'sector_analysis': [
                    SummarySection(title='Sector Analysis Summary', snippet=context.sector_analysis_summary)
                ] if context.sector_analysis_summary else [],
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
                'search_errors': [f'Pipeline summarization failed: {str(e)}']
            })

    def get_prompts(self) -> Dict[str, Any]:
        """Get stored prompts for debugging."""
        return self._prompts

    def clear_prompts(self) -> None:
        """Clear all stored prompts."""
        self._prompts = {}
