from clients.google_search_client import GoogleSearchClient
from clients.gpt_client import GPTClient
from framework.logger import get_logger
from models.robinhood_models import Article, MarketResearch
from framework.configuration import Configuration

logger = get_logger(__name__)


class MarketResearchProcessor:
    """Class for fetching and processing market research data"""

    def __init__(
        self,
        configuration: Configuration,
        google_search_client: GoogleSearchClient,
        gpt_client: GPTClient
    ):
        """
        Initialize the market research processor

        Args:
            google_search_client: Client for Google search operations
            gpt_client: Client for GPT operations
        """
        self._google_search_client = google_search_client
        self._gpt_client = gpt_client
        self._prompts = {}

        self._exclude_sites = configuration.robinhood.get('daily_pulse', {}).get('exclude_sites', [])
        self._rss_feeds = configuration.robinhood.get('daily_pulse', {}).get('rss_feeds', [])

    async def get_market_research_data(self, portfolio_data: dict) -> MarketResearch:
        """
        Fetch market research data including current market conditions and stock-specific news

        Args:
            portfolio_data: Portfolio data containing holdings

        Returns:
            Dict with market research data
        """
        logger.info('Gathering market research data')

        try:
            research_data = {
                'market_conditions': [],
                'stock_news': {},
                'sector_analysis': [],
                'search_errors': []
            }

            # Fetch general market news from RSS feeds
            await self._fetch_rss_feeds(research_data)

            # Fetch market conditions via Google search
            await self._fetch_market_conditions(research_data)

            # Fetch stock-specific news for holdings
            await self._fetch_stock_news(portfolio_data, research_data)

            # Fetch sector analysis
            await self._fetch_sector_analysis(research_data)

            # Fetch full article content for all sources
            await self._fetch_article_content(research_data)

            logger.info('Market research data gathering completed')
            return MarketResearch.model_validate(research_data)

        except Exception as e:
            logger.error(f'Error gathering market research data: {str(e)}')
            # Return empty research data structure so the method can continue
            return MarketResearch.model_validate({
                'market_conditions': [],
                'stock_news': {},
                'sector_analysis': [],
                'search_errors': [f'Overall research gathering failed: {str(e)}']
            })

    async def _fetch_rss_feeds(self, research_data):
        """Fetch market news from RSS feeds"""
        import feedparser
        # Use config or fallback to defaults
        rss_feeds = self._rss_feeds or [
            'https://www.cnbc.com/id/100003114/device/rss/rss.html',
            'https://feeds.a.dj.com/rss/RSSMarketsMain.xml',
            'https://www.reutersagency.com/feed/?best-sectors=markets&post_type=best',
        ]
        rss_articles = []
        for url in rss_feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:10]:
                    rss_articles.append({
                        'title': entry.get('title', ''),
                        'snippet': entry.get('summary', ''),
                        'link': entry.get('link', ''),
                        'source': feed.feed.get('title', ''),
                    })
            except Exception as e:
                logger.warning(f'Failed to fetch/parse RSS feed {url}: {e}')
                research_data['search_errors'].append(f'RSS feed error: {url} - {e}')
        if rss_articles:
            research_data['market_conditions'].extend(rss_articles)

    async def _fetch_market_conditions(self, research_data):
        """Fetch market conditions via Google search"""
        try:
            market_conditions = await self._google_search_client.search_market_conditions(exclude_sites=self._exclude_sites)
            if market_conditions:
                research_data['market_conditions'].extend(market_conditions)
        except Exception as e:
            logger.warning(f'Failed to fetch market conditions: {e}')
            research_data['search_errors'].append(f'Market conditions search failed: {e}')

    async def _fetch_stock_news(self, portfolio_data, research_data):
        """Fetch stock-specific news for holdings"""
        holdings = portfolio_data.get('holdings', {})
        for symbol in holdings.keys():
            try:
                news = await self._google_search_client.search_finance_news(symbol, exclude_sites=self._exclude_sites)
                if news:
                    research_data['stock_news'][symbol] = news
                    logger.info(f'Found {len(news)} news articles for {symbol}')
            except Exception as e:
                logger.warning(f'Failed to fetch news for {symbol}: {e}')
                research_data['search_errors'].append(f'News search for {symbol} failed: {e}')

    async def _fetch_sector_analysis(self, research_data):
        """Fetch sector analysis"""
        major_sectors = ['technology', 'healthcare', 'finance', 'energy']
        for sector in major_sectors:
            try:
                analysis = await self._google_search_client.search_sector_analysis(sector, exclude_sites=self._exclude_sites)
                if analysis:
                    research_data['sector_analysis'].extend(analysis)
                    logger.info(f'Found {len(analysis)} {sector} sector articles')
            except Exception as e:
                logger.warning(f'Failed to fetch {sector} sector analysis: {e}')
                research_data['search_errors'].append(f'{sector} sector analysis failed: {e}')

    async def _fetch_article_content(self, research_data):
        """Fetch full article content for all sources"""
        # Market conditions
        for article in research_data['market_conditions']:
            # Defensive: ensure article is a dict before using .get
            if not isinstance(article, dict):
                try:
                    article = dict(article)
                except Exception:
                    continue
            url = article.get('link')
            if url:
                content = await self._google_search_client.fetch_article_content(url)
                if content:
                    article['content'] = content
                else:
                    article['content'] = None

        # Stock news
        for symbol, articles in research_data['stock_news'].items():
            for article in articles:
                if not isinstance(article, dict):
                    try:
                        article = dict(article)
                    except Exception:
                        continue
                url = article.get('link')
                if url:
                    content = await self._google_search_client.fetch_article_content(url)
                    if content:
                        article['content'] = content
                    else:
                        article['content'] = None

        # Sector analysis
        for article in research_data['sector_analysis']:
            if not isinstance(article, dict):
                try:
                    article = dict(article)
                except Exception:
                    continue
            url = article.get('link')
            if url:
                content = await self._google_search_client.fetch_article_content(url)
                if content:
                    article['content'] = content
                else:
                    article['content'] = None

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

        # Summarize market conditions
        market_conditions = market_research.market_conditions
        if market_conditions:
            mc_summary = await self._summarize_market_conditions(market_conditions)
            summary['market_conditions'] = [{
                'title': 'Market Conditions Summary',
                'snippet': mc_summary
            }]

        # Summarize stock news per symbol
        stock_news = market_research.stock_news
        summary['stock_news'] = {}
        self._prompts['stock_news'] = {}

        for symbol, articles in stock_news.items():
            if not articles:
                continue
            sn_summary = await self._summarize_stock_news(symbol, articles)
            summary['stock_news'][symbol] = [{
                'title': f'{symbol} News Summary',
                'snippet': sn_summary
            }]

        # Summarize sector analysis
        sector_analysis = market_research.sector_analysis
        self._prompts['sector_analysis'] = []

        if sector_analysis:
            sa_summary = await self._summarize_sector_analysis(sector_analysis)
            summary['sector_analysis'] = [{
                'title': 'Sector Analysis Summary',
                'snippet': sa_summary
            }]
        else:
            summary['sector_analysis'] = []

        # Pass through search errors
        summary['search_errors'] = market_research.search_errors

        return MarketResearch.model_validate(summary)

    async def _summarize_market_conditions(self, market_conditions):
        """Summarize market conditions articles"""
        # Dynamically chunk based on prompt length (max ~10,000 chars per chunk for turbo)
        max_chunk_chars = 10000
        chunks = self._chunk_articles(market_conditions, max_chunk_chars)

        chunk_summaries = []
        logger.info(f"Summarizing {len(chunks)} chunks of market conditions articles")
        self._prompts['market_conditions_chunks'] = []

        for chunk in chunks:
            prompt_lines = [
                "Summarize the following market conditions articles in a concise, clear paragraph. Highlight key trends and sentiment. Ignore and do not include any marketing, advertising, or subscription messages (such as 'subscribe to CNBC for updates', etc). Only summarize actual news content.\n"
            ]

            for i, article in enumerate(chunk, 1):
                prompt_lines.append(f"{i}. {article.title}")
                if article.snippet:
                    prompt_lines.append(f"   {article.snippet}")
                if article.source:
                    prompt_lines.append(f"   Source: {article.source}")
                if article.content:
                    prompt_lines.append(f"   Content: {article.content}")
                prompt_lines.append("")

            prompt = "\n".join(prompt_lines)
            logger.info(f'Prompt for chunk summary: {prompt[:100]}...')  # Log first 100 chars of prompt

            resp_content = await self._gpt_client.generate_completion(
                prompt=prompt,
                model="gpt-4o-mini"
            )

            chunk_summaries.append(resp_content)
            self._prompts['market_conditions_chunks'].append(prompt)
            logger.info(f'Chunk summarized successfully: {resp_content[:100]}...')  # Log first 100 chars of summary

        if len(chunk_summaries) == 1:
            return chunk_summaries[0]
        else:
            # Summarize the chunk summaries into a final summary
            final_prompt = "Summarize the following summaries into a single concise, clear paragraph. Ignore and do not include any marketing, advertising, or subscription messages.\n\n"
            for i, chunk_summary in enumerate(chunk_summaries, 1):
                final_prompt += f"Summary {i}: {chunk_summary}\n"

            resp_content = await self._gpt_client.generate_completion(
                prompt=final_prompt,
                model="gpt-4o-mini"
            )

            self._prompts['market_conditions_chunks'].append(final_prompt)
            return resp_content

    def _chunk_articles(self, articles: list[Article], max_chunk_chars):
        """Split articles into chunks based on max character limit"""
        chunks = []
        current_chunk = []
        current_len = 0

        for article in articles:
            # Build the article block as it would appear in the prompt
            lines = [f"{article.title}"]
            if article.snippet:
                lines.append(f"   {article.snippet}")
            if article.source:
                lines.append(f"   Source: {article.source}")
            if article.content:
                lines.append(f"   Content: {article.content}")
            lines.append("")
            article_block = "\n".join(lines)
            block_len = len(article_block)

            if current_len + block_len > max_chunk_chars and current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_len = 0

            current_chunk.append(article)
            current_len += block_len

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    async def _summarize_stock_news(self, symbol, articles: list[Article]):
        """Summarize news for a specific stock symbol"""
        prompt_lines = [f"Summarize the following news for {symbol} in 2-3 sentences.\n"]

        for i, article in enumerate(articles, 1):
            prompt_lines.append(f"{i}. {article.title}")
            if article.snippet:
                prompt_lines.append(f"   {article.snippet}")
            if article.source:
                prompt_lines.append(f"   Source: {article.source}")
            if article.content:
                prompt_lines.append(f"   Content: {article.content}")
            prompt_lines.append("")

        prompt = "\n".join(prompt_lines)
        self._prompts['stock_news'][symbol] = prompt

        resp_content = await self._gpt_client.generate_completion(
            prompt=prompt,
            model="gpt-4o-mini"
        )

        return resp_content

    async def _summarize_sector_analysis(self, sector_analysis):
        """Summarize sector analysis articles"""
        prompt_lines = [
            "Summarize the following sector analysis articles in a few concise paragraphs.\n"
        ]

        for i, article in enumerate(sector_analysis, 1):
            prompt_lines.append(f"{i}. {article.get('title', '')}")
            if article.get('sector'):
                prompt_lines.append(f"   Sector: {article.get('sector', '').title()}")
            if article.get('snippet'):
                prompt_lines.append(f"   {article.get('snippet', '')}")
            prompt_lines.append("")

        prompt = "\n".join(prompt_lines)
        self._prompts['sector_analysis'] = [prompt]

        resp_content = await self._gpt_client.generate_completion(
            prompt=prompt,
            model="gpt-4o-mini"
        )

        return resp_content

    def get_prompts(self) -> dict:
        """Get all prompts used in summarization"""
        return self._prompts

    def clear_prompts(self) -> None:
        """Clear all prompts"""
        self._prompts = {}
