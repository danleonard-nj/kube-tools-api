from typing import Dict, List, Optional
import logging
from cachetools import cached
from framework.configuration import Configuration
from framework.logger import get_logger
from httpx import AsyncClient
import os
import openai
from bs4 import BeautifulSoup
from readability import Document
import httpx
import asyncio
import tenacity
from framework.clients.cache_client import CacheClientAsync
from models.robinhood_models import Article

logger = get_logger(__name__)


class GoogleSearchException(Exception):
    def __init__(self, query: str, message: str = None):
        super().__init__(f'Failed to search for query: {query}. {message or ""}')


class GoogleSearchClient:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient,
        cache_client: CacheClientAsync
    ):
        self._http_client = http_client
        self._cache_client = cache_client

        # Google Custom Search API configuration
        self._api_key = configuration.google_search.get('api_key')
        self._search_engine_id = configuration.google_search.get('search_engine_id')
        self._base_url = 'https://www.googleapis.com/customsearch/v1'

    def _append_exclude_sites_to_query(self, query, exclude_sites):
        """Append -site: exclusions to the query string for Google Custom Search"""
        if not exclude_sites:
            return query
        exclusion_str = ' '.join(f'-site:{site}' for site in exclude_sites)
        return f'{query} {exclusion_str}'.strip()

    async def search(
        self,
        query: str,
        num_results: int = 10,
        site_restrict: Optional[str] = None,
        exclude_sites: Optional[List[str]] = None
    ) -> Dict:
        """
        Search using Google Custom Search API

        Args:
            query: Search query string
            num_results: Number of results to return (max 10 per request)
            site_restrict: Restrict search to specific site (e.g., 'finance.yahoo.com')

        Returns:
            Dict containing search results
        """

        cache_key = f'google_search:{query}:{num_results}:{site_restrict or ""}:{"|".join(exclude_sites or [])}'
        cached_result = await self._cache_client.get_json(cache_key)
        if cached_result:
            logger.info(f'Cache hit for query: {query}: {cache_key}')
            return cached_result

        if not self._api_key or not self._search_engine_id:
            raise GoogleSearchException(query, "Google Search API key or Search Engine ID not configured")

        params = {
            'key': self._api_key,
            'cx': self._search_engine_id,
            'num': min(num_results, 10)  # Google API limits to 10 results per request
        }

        if site_restrict:
            params['siteSearch'] = site_restrict

        # Exclude sites from query if provided
        if exclude_sites:
            logger.info(f"Excluding sites: {exclude_sites}")
            for site in exclude_sites:
                query += f" -site:{site}"
        logger.info(f"Final Google query: {query}")
        params['q'] = query  # Ensure the mutated query is sent to Google

        logger.info(f'Searching for: {query}')

        try:
            response = await self._http_client.get(
                url=self._base_url,
                params=params
            )

            logger.info(f'Search response status: {response.status_code}')

            if response.status_code != 200:
                error_msg = f"API returned status {response.status_code}"
                if response.status_code == 429:
                    error_msg += " - Rate limit exceeded"
                elif response.status_code == 403:
                    error_msg += " - API key invalid or quota exceeded"

                # Cache the failure so we can skip next time
                await self._cache_client.set_json(
                    cache_key,
                    {'fail': True, 'status_code': response.status_code},
                    ttl=60  # Cache for 1 hour
                )
                raise GoogleSearchException(query, error_msg)

            data = response.json()
            # Cache the result for 1 hour
            await self._cache_client.set_json(
                cache_key,
                data,
                ttl=60  # Cache for 1 hour
            )

            return data

        except Exception as e:
            if isinstance(e, GoogleSearchException):
                raise
            logger.error(f'Error during search: {str(e)}')
            raise GoogleSearchException(query, str(e))

    async def search_market_conditions(
        self,
        exclude_sites: Optional[list[str]] = None,
        max_results=5
    ) -> list[Article]:
        """
        Search for current market conditions and trends

        Returns:
            List of market analysis articles
        """
        logger.info('search_market_conditions called')
        queries = [
            "stock market today analysis",
            "market trends 2025",
            "economic indicators today"
        ]

        all_articles = []
        for query in queries:
            logger.info(f'Running market conditions query: {query}')
            try:
                query = self._append_exclude_sites_to_query(query, exclude_sites)
                result = await self.search(
                    query=query,
                    num_results=max_results,
                    exclude_sites=exclude_sites
                )
                logger.info(f'Google API raw result for query "{query}": {result}')
                items = result.get('items', [])
                logger.info(f'Found {len(items)} items for query "{query}"')
                for item in items:
                    all_articles.append(Article(
                        title=item.get('title', ''),
                        link=item.get('link', ''),
                        snippet=item.get('snippet', ''),
                        source=item.get('displayLink', ''),
                        # query_type is not a field on Article, so skip it
                    ))
            except Exception as e:
                logger.error(f'Error searching market conditions for query "{query}": {str(e)}')
                continue
        logger.info(f'search_market_conditions returning {len(all_articles)} articles')
        return all_articles

    async def search_finance_news(
        self,
        stock_symbol: str,
        additional_terms: str = "",
        exclude_sites: Optional[List[str]] = None,
        max_results: int = 10
    ) -> List[Article]:
        """
        Search for financial news about a specific stock

        Args:
            stock_symbol: Stock symbol (e.g., 'AAPL', 'TSLA')
            additional_terms: Additional search terms

        Returns:
            List of news articles with title, link, and snippet
        """
        query = f"{stock_symbol} stock news {additional_terms}".strip()

        try:
            result = await self.search(
                query=query,
                num_results=max_results,
                exclude_sites=exclude_sites
            )

            items = result.get('items', [])
            news_articles = []

            for item in items:
                news_articles.append(Article(
                    title=item.get('title', ''),
                    link=item.get('link', ''),
                    snippet=item.get('snippet', ''),
                    source=item.get('displayLink', ''),
                ))

            return news_articles

        except Exception as e:
            logger.error(f'Error searching finance news for {stock_symbol}: {str(e)}')
            return []

    async def search_sector_analysis(self, sector: str, exclude_sites: Optional[List[str]] = None, max_results=10) -> List[Article]:
        """
        Search for sector-specific analysis

        Args:
            sector: Sector name (e.g., 'technology', 'healthcare', 'finance')

        Returns:
            List of sector analysis articles
        """
        query = f"{sector} sector analysis stocks performance"

        try:
            query = self._append_exclude_sites_to_query(query, exclude_sites)
            result = await self.search(
                query=query,
                num_results=max_results,
                exclude_sites=exclude_sites
            )

            items = result.get('items', [])
            articles = []

            for item in items:
                articles.append(Article(
                    title=item.get('title', ''),
                    link=item.get('link', ''),
                    snippet=item.get('snippet', ''),
                    source=item.get('displayLink', ''),
                    sector=sector
                ))

            return articles

        except Exception as e:
            logger.error(f'Error searching sector analysis for {sector}: {str(e)}')
            return []

    async def summarize_articles_with_openai(self, articles: List[Dict], model: str = "gpt-3.5-turbo", fetch_content_fn=None) -> str:
        """
        Summarize a list of news articles using the OpenAI SDK (gpt-3.5-turbo or specified model), with chunking for large lists.
        Optionally fetch article content in parallel using asyncio.gather and a semaphore.
        """
        if not articles:
            return "No articles to summarize."

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable not set.")

        client = openai.AsyncOpenAI(api_key=api_key)
        chunk_size = 5
        semaphore = asyncio.Semaphore(12)
        article_chunks = [articles[i:i+chunk_size] for i in range(0, len(articles), chunk_size)]
        chunk_summaries = []

        def is_retryable_exception(exc):
            import openai
            import httpx
            return isinstance(exc, (
                openai.RateLimitError,
                openai.APIError,
                httpx.HTTPStatusError,
                httpx.RequestError,
                Exception  # fallback for transient network errors
            ))

        @tenacity.retry(
            retry=tenacity.retry_if_exception(is_retryable_exception),
            wait=tenacity.wait_exponential_jitter(initial=2, max=20),
            stop=tenacity.stop_after_attempt(5),
            reraise=True,
            before_sleep=tenacity.before_sleep_log(logger, logging.WARNING)
        )
        async def openai_chat_completion(**kwargs):
            return await client.chat.completions.create(**kwargs)

        async def summarize_chunk(chunk):
            # Optionally fetch content for each article in the chunk
            if fetch_content_fn:
                async def fetch_with_semaphore(article):
                    async with semaphore:
                        content = await fetch_content_fn(article.get('link'))
                        if content:
                            article['content'] = content
                    return article
                await asyncio.gather(*(fetch_with_semaphore(article) for article in chunk))

            prompt_lines = [
                "Summarize the following news articles in a concise, clear paragraph. Highlight key trends, events, and overall sentiment.\n"
            ]
            for i, article in enumerate(chunk, 1):
                prompt_lines.append(f"{i}. {article.title}")
                if article.snippet:
                    prompt_lines.append(f"   {article.snippet}")
                if article.source:
                    prompt_lines.append(f"   Source: {article.source}")
                if article.content:
                    prompt_lines.append(f"   Content: {article.content[:300]}")
                prompt_lines.append("")
            prompt = "\n".join(prompt_lines)
            response = await openai_chat_completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            return response.choices[0].message.content.strip()

        # Summarize all chunks in parallel (with concurrency limit)
        chunk_summaries = await asyncio.gather(*(summarize_chunk(chunk) for chunk in article_chunks))

        if len(chunk_summaries) == 1:
            return chunk_summaries[0]
        else:
            # Summarize the chunk summaries into a final summary
            final_prompt = "Summarize the following summaries into a single concise, clear paragraph.\n\n"
            for i, summary in enumerate(chunk_summaries, 1):
                final_prompt += f"Summary {i}: {summary}\n"
            response = await openai_chat_completion(
                model=model,
                messages=[{"role": "user", "content": final_prompt}],
                temperature=0.7
            )
            return response.choices[0].message.content.strip()

    async def fetch_article_content(self, url: str) -> Optional[str]:
        """
        Fetch and extract the main content from a news article URL.
        Returns the main text content, or None if extraction fails.
        """
        logger.info(f'Fetching article content from URL: {url}')

        cache_key = f'article_content:{url}'
        cached_content = await self._cache_client.get_cache(cache_key)

        if cached_content:
            if isinstance(cached_content, str) and cached_content.startswith('fail-'):
                logger.info(f'Skipping fetch for {url} due to previous failure: {cached_content}')
                return None
            logger.info(f'Cache hit for article content: {url} [length={len(cached_content)}]')
            return cached_content

        logger.info(f'Cache miss for article content: {url}, fetching from web')

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        text = None
        try:
            async with httpx.AsyncClient(timeout=10, headers=headers) as client:
                resp = await client.get(url)
                logger.info(f'HTTP GET {url} status: {resp.status_code}')
                if resp.status_code == 200:
                    logger.info(f'Parsing article HTML for {url}')
                    doc = Document(resp.text)
                    html = doc.summary()
                    soup = BeautifulSoup(html, 'lxml')
                    text = soup.get_text(separator='\n', strip=True)
                    if text:
                        preview = text[:100].replace('\n', ' ')
                        logger.info(f'Extracted content for {url} (first 100 chars): {preview}... [length={len(text)}]')
                    else:
                        logger.info(f'No text extracted from article at {url}')

                    if text:
                        await self._cache_client.set_cache(
                            cache_key,
                            text,
                            ttl=60)
                    return text
                else:
                    logger.info(f'!! Failed to fetch article URL {url}: status {resp.status_code}')
                    await self._cache_client.set_cache(
                        cache_key,
                        f'fail-{resp.status_code}',
                        ttl=60)
                    return None
        except Exception as e:
            logger.warning(f'Error fetching article content from {url}: {e}', exc_info=True)
            await self._cache_client.set_cache(
                cache_key,
                'fail',
                ttl=60)
            return None
