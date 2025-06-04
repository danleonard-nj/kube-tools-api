from abc import ABC, abstractmethod
from clients.google_search_client import GoogleSearchClient
from clients.gpt_client import GPTClient
from framework.logger import get_logger
from models.robinhood_models import Article, MarketResearch, RobinhoodConfig, SummarySection, MarketResearchSummary
from framework.configuration import Configuration

logger = get_logger(__name__)


DEFAULT_RSS_FEEDS = []
MAX_ARTICLE_CHUNK_SIZE = 10000  # Max characters per chunk for GPT summarization


class BaseResearchProcessor(ABC):
    def __init__(self, gpt_client, max_chunk_chars=MAX_ARTICLE_CHUNK_SIZE):
        self._gpt_client = gpt_client
        self._max_chunk_chars = max_chunk_chars
        self._prompts = {}

    def _chunk_articles(self, articles: list, max_chunk_chars=None):
        if max_chunk_chars is None:
            max_chunk_chars = self._max_chunk_chars
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

    @abstractmethod
    async def summarize(self, *args, **kwargs):
        pass

    def get_prompts(self):
        return self._prompts

    def clear_prompts(self):
        self._prompts = {}


class MarketConditionsProcessor(BaseResearchProcessor):
    def __init__(
        self,
        gpt_client: GPTClient,
        google_search_client: GoogleSearchClient,
        config: RobinhoodConfig
    ):
        super().__init__(gpt_client)
        self._google_search_client = google_search_client
        self._exclude_sites = config.daily_pulse.exclude_sites
        self._market_condition_max_results = config.daily_pulse.search.market_condition_max_results

    async def fetch_and_enrich(self):
        market_conditions = await self._google_search_client.search_market_conditions(
            exclude_sites=self._exclude_sites,
            max_results=self._market_condition_max_results)
        filtered = [a for a in (market_conditions or []) if not self._is_excluded(a.link)]
        articles = [Article(title=a.title, snippet=a.snippet, link=a.link, source=a.source, content=None) for a in filtered]
        # Enrich with content
        for article in articles:
            if article.link:
                content = await self._google_search_client.fetch_article_content(article.link)
                article.content = content if content else None
        return articles, []

    def _is_excluded(self, url):
        if not url:
            return False
        for site in self._exclude_sites:
            if site in url:
                return True
        return False

    async def summarize(self, market_conditions):
        logger.info(f"[MarketConditionsProcessor] Summarizing {len(market_conditions)} articles")
        max_chunk_chars = self._max_chunk_chars
        chunks = self._chunk_articles(market_conditions, max_chunk_chars)
        logger.info(f"[MarketConditionsProcessor] Chunked into {len(chunks)} chunks")
        chunk_summaries = []
        self._prompts['market_conditions_chunks'] = []
        for idx, chunk in enumerate(chunks):
            logger.info(f"[MarketConditionsProcessor] Building prompt for chunk {idx+1} with {len(chunk)} articles")
            prompt_lines = [
                "Summarize the following market conditions articles in a concise, clear paragraph. Highlight key trends and sentiment. Ignore and do not include any marketing, advertising, or subscription messages (such as 'subscribe to CNBC for updates', etc). Only summarize actual news content.\n"
            ]
            for i, article in enumerate(chunk, 1):
                prompt_lines.append(article.to_prompt_block(i))
                prompt_lines.append("")
            prompt = "\n".join(prompt_lines)
            self._prompts['market_conditions_chunks'].append(prompt)
            logger.info(f"[MarketConditionsProcessor] Sending prompt for chunk {idx+1} to GPT")
            resp_content = await self._gpt_client.generate_completion(
                prompt=prompt,
                model="gpt-4o-mini"
            )
            logger.info(f"[MarketConditionsProcessor] Received summary for chunk {idx+1}")
            chunk_summaries.append(resp_content)
        if len(chunk_summaries) == 1:
            return chunk_summaries[0]
        else:
            final_prompt = "Summarize the following summaries into a single concise, clear paragraph. Ignore and do not include any marketing, advertising, or subscription messages.\n\n"
            for i, chunk_summary in enumerate(chunk_summaries, 1):
                final_prompt += f"Summary {i}: {chunk_summary}\n"
            self._prompts['market_conditions_chunks'].append(final_prompt)
            logger.info(f"[MarketConditionsProcessor] Sending final merge prompt to GPT")
            resp_content = await self._gpt_client.generate_completion(
                prompt=final_prompt,
                model="gpt-4o-mini"
            )
            logger.info(f"[MarketConditionsProcessor] Received merged summary")
            return resp_content


class StockNewsProcessor(BaseResearchProcessor):
    def __init__(
        self,
        gpt_client: GPTClient,
        google_search_client: GoogleSearchClient,
        config: RobinhoodConfig
    ):
        super().__init__(gpt_client)
        self._google_search_client = google_search_client
        self._exclude_sites = config.daily_pulse.exclude_sites
        self._max_results = config.daily_pulse.search.stock_news_max_results

    async def fetch_and_enrich(self, portfolio_data):
        holdings = portfolio_data.get('holdings', {})
        stock_news = {}
        for symbol in holdings.keys():
            news = await self._google_search_client.search_finance_news(
                symbol,
                exclude_sites=self._exclude_sites,
                max_results=self._max_results)
            filtered = [a for a in (news or []) if not self._is_excluded(a.link)]
            articles = [Article(title=a.title, snippet=a.snippet, link=a.link, source=a.source, content=None) for a in filtered]
            # Enrich with content
            for article in articles:
                if article.link:
                    content = await self._google_search_client.fetch_article_content(article.link)
                    article.content = content if content else None
            if articles:
                stock_news[symbol] = articles
                logger.info(f'Found {len(articles)} news articles for {symbol}')
        return stock_news, []

    def _is_excluded(self, url):
        if not url:
            return False
        for site in self._exclude_sites:
            if site in url:
                return True
        return False

    async def summarize(self, symbol, articles):
        logger.info(f"[StockNewsProcessor] Summarizing {len(articles)} articles for symbol {symbol}")
        prompt_lines = [f"Summarize the following news for {symbol} in 2-3 sentences.\n"]
        for i, article in enumerate(articles, 1):
            prompt_lines.append(article.to_prompt_block(i))
            prompt_lines.append("")
        prompt = "\n".join(prompt_lines)
        self._prompts.setdefault('stock_news', {})[symbol] = prompt
        logger.info(f"[StockNewsProcessor] Sending prompt for {symbol} to GPT")
        resp_content = await self._gpt_client.generate_completion(
            prompt=prompt,
            model="gpt-4o-mini"
        )
        logger.info(f"[StockNewsProcessor] Received summary for {symbol}")
        return resp_content


class SectorAnalysisProcessor(BaseResearchProcessor):
    def __init__(
        self,
        gpt_client: GPTClient,
        google_search_client: GoogleSearchClient,
        config: RobinhoodConfig
    ):
        super().__init__(gpt_client)
        self._google_search_client = google_search_client
        self._exclude_sites = config.daily_pulse.exclude_sites
        self._max_results = config.daily_pulse.search.sector_analysis_max_results

    async def fetch_and_enrich(self):
        major_sectors = ['technology', 'healthcare', 'finance', 'energy']
        sector_analysis = []
        for sector in major_sectors:
            analysis = await self._google_search_client.search_sector_analysis(
                sector,
                exclude_sites=self._exclude_sites,
                max_results=self._max_results)
            filtered = [a for a in (analysis or []) if not self._is_excluded(a.link)]
            articles = [Article(title=a.title, snippet=a.snippet, link=a.link, source=a.source, content=None, sector=a.sector) for a in filtered]
            for article in articles:
                if article.link:
                    content = await self._google_search_client.fetch_article_content(article.link)
                    article.content = content if content else None
            if articles:
                sector_analysis.extend(articles)
                logger.info(f'Found {len(articles)} {sector} sector articles')
        return sector_analysis, []

    def _is_excluded(self, url):
        if not url:
            return False
        for site in self._exclude_sites:
            if site in url:
                return True
        return False

    async def summarize(self, sector_analysis):
        logger.info(f"[SectorAnalysisProcessor] Summarizing {len(sector_analysis)} sector analysis articles")
        prompt_lines = [
            "Summarize the following sector analysis articles in a few concise paragraphs.\n"
        ]
        for i, article in enumerate(sector_analysis, 1):
            if hasattr(article, 'to_prompt_block'):
                prompt_lines.append(article.to_prompt_block(i))
            else:
                prompt_lines.append(Article.dict_to_prompt_block(article, i))
            prompt_lines.append("")
        prompt = "\n".join(prompt_lines)
        self._prompts['sector_analysis'] = [prompt]
        logger.info(f"[SectorAnalysisProcessor] Sending prompt to GPT")
        resp_content = await self._gpt_client.generate_completion(
            prompt=prompt,
            model="gpt-4o-mini"
        )
        logger.info(f"[SectorAnalysisProcessor] Received summary")
        return resp_content


class RssNewsProcessor(BaseResearchProcessor):
    def __init__(
        self,
        gpt_client: GPTClient,
        google_search_client: GoogleSearchClient,
        config: RobinhoodConfig
    ):
        super().__init__(gpt_client)
        self._google_search_client = google_search_client
        self._rss_feeds = config.daily_pulse.rss_feeds
        self._rss_content_fetch_limit = getattr(config.daily_pulse, 'rss_content_fetch_limit', 5)  # Default to 5 if not set

    async def fetch_and_enrich(self):
        import feedparser
        rss_feeds = self._rss_feeds or DEFAULT_RSS_FEEDS
        rss_articles = []
        for url in rss_feeds:
            logger.info(f'Processing RSS feed: {url}')
            feed = feedparser.parse(url)
            for idx, entry in enumerate(feed.entries[:10]):
                article = Article(
                    title=entry.get('title', ''),
                    snippet=entry.get('summary', ''),
                    link=entry.get('link', ''),
                    source=feed.feed.get('title', ''),
                    content=None
                )
                link = article.link
                if link and idx < self._rss_content_fetch_limit:
                    logger.info(f'Fetching content for RSS article: {link}')
                    content = await self._google_search_client.fetch_article_content(link)
                    article.content = content if content else None
                else:
                    article.content = None
                rss_articles.append(article)
        return rss_articles, []

    async def summarize(self, rss_articles):
        logger.info(f"[RssNewsProcessor] Summarizing {len(rss_articles)} RSS articles")
        max_chunk_chars = self._max_chunk_chars
        chunks = self._chunk_articles(rss_articles, max_chunk_chars)
        logger.info(f"[RssNewsProcessor] Chunked into {len(chunks)} chunks")
        chunk_summaries = []
        self._prompts['rss_news_chunks'] = []
        for idx, chunk in enumerate(chunks):
            logger.info(f"[RssNewsProcessor] Building prompt for chunk {idx+1} with {len(chunk)} articles")
            prompt_lines = [
                "Summarize the following RSS news articles in a concise, clear paragraph. Highlight key trends and sentiment. Ignore and do not include any marketing, advertising, or subscription messages (such as 'subscribe to CNBC for updates', etc). Only summarize actual news content.\n"
            ]
            for i, article in enumerate(chunk, 1):
                prompt_lines.append(article.to_prompt_block(i))
                prompt_lines.append("")
            prompt = "\n".join(prompt_lines)
            self._prompts['rss_news_chunks'].append(prompt)
            logger.info(f"[RssNewsProcessor] Sending prompt for chunk {idx+1} to GPT")
            resp_content = await self._gpt_client.generate_completion(
                prompt=prompt,
                model="gpt-4o-mini"
            )
            logger.info(f"[RssNewsProcessor] Received summary for chunk {idx+1}")
            chunk_summaries.append(resp_content)
        if len(chunk_summaries) == 1:
            return chunk_summaries[0]
        else:
            final_prompt = "Summarize the following summaries into a single concise, clear paragraph. Ignore and do not include any marketing, advertising, or subscription messages.\n\n"
            for i, chunk_summary in enumerate(chunk_summaries, 1):
                final_prompt += f"Summary {i}: {chunk_summary}\n"
            self._prompts['rss_news_chunks'].append(final_prompt)
            logger.info(f"[RssNewsProcessor] Sending final merge prompt to GPT")
            resp_content = await self._gpt_client.generate_completion(
                prompt=final_prompt,
                model="gpt-4o-mini"
            )
            logger.info(f"[RssNewsProcessor] Received merged summary")
            return resp_content


class MarketResearchProcessor:
    """Class for fetching and processing market research data"""

    def __init__(
        self,
        configuration: Configuration,
        google_search_client: GoogleSearchClient,
        gpt_client: GPTClient,
        robinhood_config: RobinhoodConfig,
        market_conditions_processor: MarketConditionsProcessor = None,
        stock_news_processor: StockNewsProcessor = None,
        sector_analysis_processor: SectorAnalysisProcessor = None,
        rss_news_processor: RssNewsProcessor = None
    ):
        self._google_search_client = google_search_client
        self._gpt_client = gpt_client
        self._robinhood_config = robinhood_config
        self._exclude_sites = configuration.robinhood.get('daily_pulse', {}).get('exclude_sites', [])
        self._rss_feeds = configuration.robinhood.get('daily_pulse', {}).get('rss_feeds', [])
        self._search_config = getattr(self._robinhood_config, 'daily_pulse', None).search if hasattr(getattr(self._robinhood_config, 'daily_pulse', None), 'search') else None

        self._market_conditions_processor = market_conditions_processor
        self._stock_news_processor = stock_news_processor
        self._sector_analysis_processor = sector_analysis_processor
        self._rss_news_processor = rss_news_processor

    async def get_market_research_data(self, portfolio_data: dict) -> MarketResearch:
        logger.info('Gathering market research data')
        try:
            # rss_processor = RssNewsProcessor(self._gpt_client, self._google_search_client, self._rss_feeds)
            # mc_processor = MarketConditionsProcessor(self._gpt_client, self._google_search_client, self._exclude_sites, search_config=self._search_config)
            # sn_processor = StockNewsProcessor(self._gpt_client, self._google_search_client, self._exclude_sites, search_config=self._search_config)
            # sa_processor = SectorAnalysisProcessor(self._gpt_client, self._google_search_client, self._exclude_sites, search_config=self._search_config)

            # Fetch and enrich all data
            rss_articles, rss_errors = await self._rss_news_processor.fetch_and_enrich()
            market_conditions, market_condition_errors = await self._market_conditions_processor.fetch_and_enrich()
            stock_news, stock_news_errors = await self._stock_news_processor.fetch_and_enrich(portfolio_data)
            sector_analysis, sector_analysis_errors = await self._sector_analysis_processor.fetch_and_enrich()

            search_errors = rss_errors + market_condition_errors + stock_news_errors + sector_analysis_errors

            research_data = {
                'market_conditions': rss_articles + market_conditions,
                'stock_news': stock_news,
                'sector_analysis': sector_analysis,
                'search_errors': search_errors
            }
            logger.info('Market research data gathering completed')
            return MarketResearch.model_validate(research_data)
        except Exception as e:
            logger.error(f'Error gathering market research data: {str(e)}')
            return MarketResearch.model_validate({
                'market_conditions': [],
                'stock_news': {},
                'sector_analysis': [],
                'search_errors': [f'Overall research gathering failed: {str(e)}']
            })

    async def summarize_market_research(self, market_research: MarketResearch) -> MarketResearch:
        """
        Summarize market research data using GPT

        Args:
            market_research: Market research data from get_market_research_data

        Returns:
            Dict with summarized market research
        """
        summary = {}
        self._prompts = {}

        # Summarize RSS news (if present)
        rss_articles = []
        market_conditions = market_research.market_conditions or []
        # Split RSS and non-RSS if needed (here, treat all as one for now)
        if market_conditions:
            rss_articles = market_conditions
        if rss_articles:
            rss_summary = await self._rss_news_processor.summarize(rss_articles)
            summary['market_conditions'] = [
                SummarySection(title='Market Conditions Summary', snippet=rss_summary)
            ]
            self._prompts['rss_news_chunks'] = self._rss_news_processor.get_prompts().get('rss_news_chunks', [])

        # Summarize stock news per symbol
        stock_news = market_research.stock_news or {}
        summary['stock_news'] = {}
        self._prompts['stock_news'] = {}
        for symbol, articles in stock_news.items():
            if not articles:
                continue
            sn_summary = await self._stock_news_processor.summarize(symbol, articles)
            summary['stock_news'][symbol] = [
                SummarySection(title=f'{symbol} News Summary', snippet=sn_summary)
            ]
            self._prompts['stock_news'][symbol] = self._stock_news_processor.get_prompts().get('stock_news', {}).get(symbol, "")

        # Summarize sector analysis
        sector_analysis = market_research.sector_analysis or []
        self._prompts['sector_analysis'] = []
        if sector_analysis:
            sa_summary = await self._sector_analysis_processor.summarize(sector_analysis)
            summary['sector_analysis'] = [
                SummarySection(title='Sector Analysis Summary', snippet=sa_summary)
            ]
            self._prompts['sector_analysis'] = self._sector_analysis_processor.get_prompts().get('sector_analysis', [])
        else:
            summary['sector_analysis'] = []

        # Pass through search errors
        summary['search_errors'] = market_research.search_errors
        return MarketResearchSummary.model_validate(summary)

    def get_prompts(self):
        return getattr(self, '_prompts', {})

    def clear_prompts(self):
        """Clear all stored prompts in the processor and its sub-processors."""
        self._prompts = {}
        if hasattr(self, '_market_conditions_processor') and self._market_conditions_processor:
            self._market_conditions_processor.clear_prompts()
        if hasattr(self, '_stock_news_processor') and self._stock_news_processor:
            self._stock_news_processor.clear_prompts()
        if hasattr(self, '_sector_analysis_processor') and self._sector_analysis_processor:
            self._sector_analysis_processor.clear_prompts()
        if hasattr(self, '_rss_news_processor') and self._rss_news_processor:
            self._rss_news_processor.clear_prompts()
