import asyncio
import datetime
import html
import json
import logging
import os
from re import sub
import openai
from framework.configuration import Configuration
import robin_stocks.robinhood as r
import feedparser

from clients.google_search_client import GoogleSearchClient
from clients.email_gateway_client import EmailGatewayClient
from data.sms_inbound_repository import InboundSMSRepository
from services.bank_service import BankService
from domain.enums import BankKey, SyncType
from framework.clients.cache_client import CacheClientAsync
from utilities.utils import DateTimeUtil
from framework.logger import get_logger
import markdown


logger = get_logger(__name__)


class RobinhoodService:
    def __init__(
        self,
        configuration: Configuration,
        inbound_sms_repository: InboundSMSRepository,
        google_search_client: GoogleSearchClient,
        bank_service: BankService,
        cache_client: CacheClientAsync,
        email_gateway_client: EmailGatewayClient
    ):
        self._inbound_sms_repository = inbound_sms_repository
        self._google_search_client = google_search_client
        self._bank_service = bank_service
        self._cache_client = cache_client
        self._email_gateway_client = email_gateway_client

        self._prompts = {}

        self._username = configuration.robinhood.get('username')
        self._password = configuration.robinhood.get('password')

        self._openai_api_key = configuration.openai.get('api_key')
        if not self._openai_api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable not set.")

    async def generate_daily_pulse(self):
        """Generate a daily pulse report for Robinhood account using OpenAI GPT-4o"""
        logger.info('Generating daily pulse report for user: %s', self._username)

        try:
            robinhood_cache_key = f"robinhood_account_data"
            portfolio_data = await self._cache_client.get_json(robinhood_cache_key)

            if not portfolio_data:
                # Login to Robinhood
                login_result = await self.login()
                if not login_result.get('success', False):
                    logger.error('Failed to login to Robinhood')
                    return {
                        'success': False,
                        'error': 'Failed to login to Robinhood'
                    }            # Fetch comprehensive Robinhood data
                portfolio_data = await self._get_portfolio_data()

                if not portfolio_data.get('success', False):
                    logger.error('Failed to fetch portfolio data')
                    return {
                        'success': False,
                        'error': 'Failed to fetch portfolio data'
                    }

                # Cache the portfolio data for 1 hour
                await self._cache_client.set_json(
                    robinhood_cache_key,
                    portfolio_data,
                    ttl=60
                )

            # Fetch market research and news data
            logger.info('Fetching market research and current news')
            market_research = await self._get_market_research_data(portfolio_data['data'])

            # Summarize market research using GPT-3.5-turbo
            summarized_market_research = await self._summarize_market_research(market_research)

            # Compile prompt for GPT-4o
            pulse_prompt = self._compile_daily_pulse_prompt_openai(portfolio_data['data'], summarized_market_research)
            self._prompts['pulse_prompt'] = pulse_prompt

            # Use OpenAI GPT-4o for main analysis
            client = openai.AsyncOpenAI(api_key=self._openai_api_key)
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": pulse_prompt}],
                temperature=0.7
            )
            pulse_analysis = response.choices[0].message.content.strip()

            await self.send_daily_pulse_email(
                to_email='dcl525@gmail.com',
                analysis=pulse_analysis,
                portfolio_summary=portfolio_data['data'],
                market_research=summarized_market_research
            )

            return {
                'success': True,
                'data': {
                    'analysis': pulse_analysis,
                    'portfolio_summary': portfolio_data['data'],
                    'generated_at': DateTimeUtil.get_iso_date(),
                    'market_research': summarized_market_research
                }
            }

        except Exception as e:
            logger.error('Error generating daily pulse: %s', str(e))
            return {
                'success': False,
                'error': str(e)
            }

    async def _summarize_market_research(self, market_research):
        """Summarize market research/news using OpenAI GPT-3.5-turbo"""
        client = openai.AsyncOpenAI(api_key=self._openai_api_key)
        summary = {}

        # Summarize market conditions
        market_conditions = market_research.get('market_conditions', [])
        if market_conditions:
            # Dynamically chunk based on prompt length (max ~10,000 chars per chunk for turbo)
            max_chunk_chars = 10000
            chunks = []
            current_chunk = []
            current_len = 0
            for article in market_conditions:
                # Build the article block as it would appear in the prompt
                lines = [f"{article.get('title', '')}"]
                if article.get('snippet'):
                    lines.append(f"   {article.get('snippet', '')}")
                if article.get('source'):
                    lines.append(f"   Source: {article.get('source', '')}")
                if article.get('content'):
                    lines.append(f"   Content: {article.get('content','')}")
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
            chunk_summaries = []
            logger.info(f"Summarizing {len(chunks)} chunks of market conditions articles")
            self._prompts['market_conditions_chunks'] = []
            for chunk in chunks:
                prompt_lines = [
                    "Summarize the following market conditions articles in a concise, clear paragraph. Highlight key trends and sentiment.\n"
                ]
                for i, article in enumerate(chunk, 1):
                    prompt_lines.append(f"{i}. {article.get('title', '')}")
                    if article.get('snippet'):
                        prompt_lines.append(f"   {article.get('snippet', '')}")
                    if article.get('source'):
                        prompt_lines.append(f"   Source: {article.get('source', '')}")
                    if article.get('content'):
                        prompt_lines.append(f"   Content: {article.get('content','')}")
                    prompt_lines.append("")
                prompt = "\n".join(prompt_lines)
                logger.info(f'Prompt for chunk summary: {prompt[:100]}...')  # Log first 100 chars of prompt
                resp = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7
                )
                chunk_summaries.append(resp.choices[0].message.content.strip())
                self._prompts['market_conditions_chunks'].append(prompt)
                logger.info(f'Chunk summarized successfully: {chunk_summaries[-1][:100]}...')  # Log first 100 chars of summary
            if len(chunk_summaries) == 1:
                summary['market_conditions'] = chunk_summaries[0]
            else:
                # Summarize the chunk summaries into a final summary
                final_prompt = "Summarize the following summaries into a single concise, clear paragraph.\n\n"
                for i, chunk_summary in enumerate(chunk_summaries, 1):
                    final_prompt += f"Summary {i}: {chunk_summary}\n"
                resp = await client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": final_prompt}],
                    temperature=0.7
                )
                summary['market_conditions'] = resp.choices[0].message.content.strip()
                self._prompts['market_conditions_chunks'].append(final_prompt)

        # Summarize stock news per symbol
        stock_news = market_research.get('stock_news', {})
        summary['stock_news'] = {}
        self._prompts['stock_news'] = {}
        for symbol, articles in stock_news.items():
            if not articles:
                continue
            prompt_lines = [f"Summarize the following news for {symbol} in 2-3 sentences.\n"]
            for i, article in enumerate(articles, 1):
                prompt_lines.append(f"{i}. {article.get('title', '')}")
                if article.get('snippet'):
                    prompt_lines.append(f"   {article.get('snippet', '')}")
                if article.get('source'):
                    prompt_lines.append(f"   Source: {article.get('source', '')}")
                prompt_lines.append("")
            prompt = "\n".join(prompt_lines)
            self._prompts['stock_news'][symbol] = prompt
            resp = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            summary['stock_news'][symbol] = resp.choices[0].message.content.strip()

        # Summarize sector analysis
        sector_analysis = market_research.get('sector_analysis', [])
        self._prompts['sector_analysis'] = []
        if sector_analysis:
            prompt_lines = [
                "Summarize the following sector analysis articles in a concise paragraph.\n"
            ]
            for i, article in enumerate(sector_analysis, 1):
                prompt_lines.append(f"{i}. {article.get('title', '')}")
                if article.get('sector'):
                    prompt_lines.append(f"   Sector: {article.get('sector', '').title()}")
                if article.get('snippet'):
                    prompt_lines.append(f"   {article.get('snippet', '')}")
                prompt_lines.append("")
            prompt = "\n".join(prompt_lines)
            self._prompts['sector_analysis'].append(prompt)
            resp = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            summary['sector_analysis'] = resp.choices[0].message.content.strip()

        # Pass through search errors
        summary['search_errors'] = market_research.get('search_errors', [])

        return summary

    def _compile_daily_pulse_prompt_openai(self, portfolio_data, summarized_market_research=None):
        """Compile prompt for OpenAI GPT-4o using summarized market research"""
        # Extract key metrics
        portfolio_profile = portfolio_data.get('portfolio_profile', {})
        holdings = portfolio_data.get('holdings', {})
        account_profile = portfolio_data.get('account_profile', {})
        recent_orders = portfolio_data.get('recent_orders', [])

        # Calculate key metrics
        total_equity = portfolio_profile.get('total_return_today', '0')
        day_change = portfolio_profile.get('total_return_today', '0')
        buying_power = account_profile.get('buying_power', '0')

        # Format holdings information
        holdings_summary = []
        for symbol, data in holdings.items():
            holdings_summary.append({
                'symbol': symbol,
                'quantity': data.get('quantity', '0'),
                'average_buy_price': data.get('average_buy_price', '0'),
                'current_price': data.get('price', '0'),
                'total_return': data.get('total_return_today_equity', '0'),
                'percentage_change': data.get('percentage', '0')
            })        # Format recent orders
        recent_activity = []
        for order in recent_orders[:5]:  # Top 5 recent orders
            # Extract symbol from instrument URL if needed
            symbol = order.get('symbol', 'Unknown')
            if symbol == 'Unknown' and 'instrument' in order:
                # Get symbol from instrument data if available
                instrument_data = order.get('instrument')
                if isinstance(instrument_data, dict):
                    symbol = instrument_data.get('symbol', 'Unknown')

            recent_activity.append({
                'instrument_symbol': symbol,
                'side': order.get('side', 'Unknown'),
                'quantity': order.get('quantity', '0'),
                'price': order.get('price', '0'),
                'state': order.get('state', 'Unknown'),
                'created_at': order.get('created_at', '')
            })

        # Format as plain text for GPT-4o
        prompt = f"""
You are a professional financial advisor and newsletter writer. Write a detailed, visually engaging, and newsletter-style daily investment pulse report. Use a friendly, expert tone. For each section, provide:
- A short narrative introduction
- Detailed bullet points with explanations
- Actionable insights and context
- Highlight notable trends, risks, and opportunities
- Add a closing summary with key takeaways and encouragement

Make the report at least 30% longer than a typical summary, and use clear section headers, emojis, and formatting cues for readability.

PORTFOLIO OVERVIEW:
- Total Equity: ${total_equity}
- Today's Change: ${day_change}
- Available Buying Power: ${buying_power}

CURRENT HOLDINGS:
"""
        for holding in holdings_summary:
            prompt += f"- {holding['symbol']}: {holding['quantity']} shares @ ${holding['average_buy_price']} (Current: ${holding['current_price']}, Change: {holding['percentage_change']}%)\n"
        prompt += "\nRECENT TRADING ACTIVITY:\n"
        for activity in recent_activity:
            prompt += f"- {activity['side'].upper()} {activity['quantity']} {activity['instrument_symbol']} @ ${activity['price']} ({activity['state']})\n"
        if summarized_market_research:
            prompt += "\nMARKET RESEARCH SUMMARY:\n"
            if summarized_market_research.get('market_conditions'):
                prompt += f"Market Conditions: {summarized_market_research['market_conditions']}\n"
            if summarized_market_research.get('stock_news'):
                for symbol, summary in summarized_market_research['stock_news'].items():
                    prompt += f"{symbol} News: {summary}\n"
            if summarized_market_research.get('sector_analysis'):
                prompt += f"Sector Analysis: {summarized_market_research['sector_analysis']}\n"
            if summarized_market_research.get('search_errors'):
                prompt += f"Note: {summarized_market_research['search_errors']}\n"
        prompt += """
\nPlease provide a comprehensive daily pulse report that includes:

1. PORTFOLIO HEALTH ASSESSMENT
   - Overall portfolio performance analysis (with narrative)
   - Risk assessment based on holdings diversity (with context)
   - Liquidity position evaluation (with suggestions)
2. TODAY'S MARKET IMPACT
   - Analysis of how current market conditions may be affecting the portfolio (with examples)
   - Sector exposure analysis (with visual cues)
   - Notable gainers and losers in the portfolio (with commentary)
3. STRATEGIC RECOMMENDATIONS
   - Suggested portfolio adjustments based on current holdings (with rationale)
   - Potential buying opportunities given current buying power (with alternatives)
   - Risk management suggestions (with practical steps)
4. MARKET OUTLOOK & OPPORTUNITIES
   - General market sentiment analysis (with trends)
   - Emerging trends that could impact current holdings (with forward-looking statements)
   - Specific stock recommendations for consideration (with reasoning)
5. ACTION ITEMS
   - Immediate actions to consider (buy/sell/hold decisions, with justifications)
   - Long-term strategic moves (with vision)
   - Risk mitigation strategies (with examples)
\nMake the analysis actionable, specific, and tailored to this portfolio's current composition. Include reasoning for all recommendations and consider both technical and fundamental analysis perspectives. Format the response in clear sections with bullet points, icons, and short paragraphs for easy reading.
\nInclude a closing section with key takeaways and a positive, motivational note.\n\nThe report should look like a premium financial newsletter!\n"""

        self._prompts['pulse_prompt'] = prompt
        return prompt

    async def _get_portfolio_data(self):
        """Fetch comprehensive portfolio data from Robinhood"""
        logger.info('Fetching comprehensive portfolio data')

        try:
            # Get account profile
            account_profile = r.profiles.load_account_profile()

            # Get portfolio profile
            portfolio_profile = r.profiles.load_portfolio_profile()

            # Get current holdings
            holdings = r.account.build_holdings()

            # Get positions (including options if any)
            positions = r.account.build_user_profile()            # Get recent orders (with error handling)
            try:
                orders = r.orders.get_all_stock_orders()
                if orders:
                    orders = orders[:10]  # Last 10 orders
                else:
                    orders = []
                    logger.warning('No orders returned from get_all_stock_orders')
            except Exception as e:
                logger.warning(f'Failed to fetch orders: {str(e)}')
                orders = []            # Get watchlist stocks for context (with error handling)
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

    async def _get_market_research_data(self, portfolio_data):
        """Fetch market research data including current market conditions and stock-specific news"""
        logger.info('Gathering market research data')

        try:
            research_data = {
                'market_conditions': [],
                'stock_news': {},
                'sector_analysis': [],
                'search_errors': []
            }

            # Fetch general market news from RSS feeds (reduce junk)
            rss_feeds = [
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

            # Await market conditions (Google search fallback)
            try:
                market_conditions = await self._google_search_client.search_market_conditions()
                if market_conditions:
                    research_data['market_conditions'].extend(market_conditions)
            except Exception as e:
                logger.warning(f'Failed to fetch market conditions: {e}')
                research_data['search_errors'].append(f'Market conditions search failed: {e}')

            # Await stock-specific news
            holdings = portfolio_data.get('holdings', {})
            for symbol in holdings.keys():
                try:
                    news = await self._google_search_client.search_finance_news(symbol)
                    if news:
                        research_data['stock_news'][symbol] = news
                        logger.info(f'Found {len(news)} news articles for {symbol}')
                except Exception as e:
                    logger.warning(f'Failed to fetch news for {symbol}: {e}')
                    research_data['search_errors'].append(f'News search for {symbol} failed: {e}')

            # Await sector analysis
            major_sectors = ['technology', 'healthcare', 'finance', 'energy']
            for sector in major_sectors:
                try:
                    analysis = await self._google_search_client.search_sector_analysis(sector)
                    if analysis:
                        research_data['sector_analysis'].extend(analysis)
                        logger.info(f'Found {len(analysis)} {sector} sector articles')
                except Exception as e:
                    logger.warning(f'Failed to fetch {sector} sector analysis: {e}')
                    research_data['search_errors'].append(f'{sector} sector analysis failed: {e}')

            # Fetch full article content for market_conditions
            for article in research_data['market_conditions']:
                url = article.get('link')
                if url:
                    content = await self._google_search_client.fetch_article_content(url)
                    if content:
                        article['content'] = content
                    else:
                        article['content'] = None

            # Fetch full article content for stock_news
            for symbol, articles in research_data['stock_news'].items():
                for article in articles:
                    url = article.get('link')
                    if url:
                        content = await self._google_search_client.fetch_article_content(url)
                        if content:
                            article['content'] = content
                        else:
                            article['content'] = None

            # Fetch full article content for sector_analysis
            for article in research_data['sector_analysis']:
                url = article.get('link')
                if url:
                    content = await self._google_search_client.fetch_article_content(url)
                    if content:
                        article['content'] = content
                    else:
                        article['content'] = None

            logger.info('Market research data gathering completed')
            return research_data

        except Exception as e:
            logger.error(f'Error gathering market research data: {str(e)}')
            # Return empty research data structure so the method can continue
            return {
                'market_conditions': [],
                'stock_news': {},
                'sector_analysis': [],
                'search_errors': [f'Overall research gathering failed: {str(e)}']
            }

    async def get_account_info(self):
        """Get account information from Robinhood"""
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
                'success': True,                'data': account_info
            }
        except Exception as e:
            logger.error('Error fetching account information: %s', str(e))
            return {
                'success': False,
                'error': str(e)
            }

    async def login(self) -> bool:
        """Login to Robinhood"""
        mfa_token = None
        logger.info('Attempting to login to Robinhood for user: %s', self._username)

        try:
            try:
                logger.debug('Calling r.login without MFA')
                r.login(
                    username=self._username,
                    password=self._password
                )
                logger.info('Login successful without MFA')
            except r.robinhood.exceptions.TwoFactorRequired as e:
                logger.warning('TwoFactorRequired exception caught: %s', str(e))
                cycles = 0
                while cycles < 5:
                    logger.info('Waiting for MFA SMS (attempt %d/5)', cycles + 1)
                    last_messages = await self._inbound_sms_repository.get_messages(limit=1)

                    if last_messages:
                        mfa_token = last_messages[0].body.strip()
                        logger.info('Received MFA token: %s', mfa_token)
                        break

                    logger.debug('No MFA SMS received, sleeping for 5 seconds')
                    await asyncio.sleep(5)  # Wait for new SMS
                    cycles += 1
                if mfa_token:
                    logger.debug('Calling r.login with MFA token')
                    r.login(
                        username=self._username,
                        password=self._password,
                        mfa_code=mfa_token
                    )
                    logger.info('Login successful with MFA')
                else:
                    logger.error('Failed to retrieve MFA token after 5 attempts')
                    return {
                        'success': False,
                        'mfa_required': True,
                        'error': 'MFA token not received'
                    }

            logger.debug('Returning login result: success=True, mfa_required=%s', mfa_token is not None)
            return {
                'success': True,
                'mfa_required': mfa_token is not None
            }
        except Exception as e:
            logger.error('Error during login: %s', str(e))
            return {
                'success': False,
                'mfa_required': False,
                'error': str(e)
            }

    def calculate_total_portfolio_value(self, portfolio_data):
        """Calculate total portfolio value from holdings data and available cash"""
        logger.info('Calculating total portfolio value')

        try:
            total_value = 0.0

            # Get account profile for cash balance
            account_profile = portfolio_data.get('account_profile', {})

            # First, try to get the total equity from portfolio profile (most accurate)
            portfolio_profile = portfolio_data.get('portfolio_profile', {})
            total_equity = portfolio_profile.get('total_equity', '0.0')
            if total_equity:
                try:
                    equity_value = float(total_equity)
                    if equity_value > 0:
                        total_value = equity_value
                        logger.debug('Using total equity as portfolio value: $%.2f', equity_value)
                        return total_value
                except (ValueError, TypeError):
                    logger.warning('Invalid total equity value: %s', total_equity)

            # If no valid equity data, calculate from individual holdings
            holdings = portfolio_data.get('holdings', {})
            for symbol, holding_data in holdings.items():
                try:
                    # First try to get market_value if available
                    market_value = holding_data.get('market_value', '0.0')
                    if market_value and market_value != '0.0':
                        holding_value = float(market_value)
                        total_value += holding_value
                        logger.debug('Added holding %s market value: $%.2f', symbol, holding_value)
                    else:
                        # Calculate from quantity and price
                        quantity = holding_data.get('quantity', '0')
                        price = holding_data.get('price', '0')
                        if quantity and price:
                            quantity_float = float(quantity)
                            price_float = float(price)
                            holding_value = quantity_float * price_float
                            total_value += holding_value
                            logger.debug('Added holding %s calculated value: %.2f * %.2f = $%.2f',
                                         symbol, quantity_float, price_float, holding_value)
                except (ValueError, TypeError) as e:
                    logger.warning('Invalid holding data for %s: %s', symbol, str(e))

            # Add available cash (try multiple cash field names)
            cash_fields = ['portfolio_cash', 'buying_power', 'cash']
            cash_added = False
            for cash_field in cash_fields:
                cash_value = account_profile.get(cash_field, '0.0')
                if cash_value and cash_value != '0.0' and not cash_added:
                    try:
                        cash_float = float(cash_value)
                        total_value += cash_float
                        logger.debug('Added cash (%s): $%.2f', cash_field, cash_float)
                        cash_added = True
                        break
                    except (ValueError, TypeError):
                        logger.warning('Invalid cash value for %s: %s', cash_field, cash_value)

            logger.info('Total portfolio value calculated: $%.2f', total_value)
            return total_value

        except Exception as e:
            logger.error('Error calculating portfolio value: %s', str(e))
            return 0.0

    async def sync_portfolio_balance(self):
        """Sync current portfolio balance with bank service"""
        logger.info('Starting portfolio balance sync')

        try:
            # Login to Robinhood
            login_result = await self.login()
            if not login_result.get('success', False):
                logger.error('Failed to login to Robinhood for balance sync')
                return {
                    'success': False,
                    'error': 'Failed to login to Robinhood'
                }

            # Get portfolio data
            portfolio_data = await self._get_portfolio_data()
            if not portfolio_data.get('success', False):
                logger.error('Failed to fetch portfolio data for balance sync')
                return {
                    'success': False,
                    'error': 'Failed to fetch portfolio data'
                }

            # Calculate total portfolio value
            total_value = self.calculate_total_portfolio_value(portfolio_data['data'])

            if total_value <= 0:
                logger.warning('Portfolio value is zero or negative: $%.2f', total_value)
                return {
                    'success': False,
                    'error': 'Invalid portfolio value calculated'
                }

            # Capture balance using bank service
            balance_record = await self._bank_service.capture_balance(
                bank_key=BankKey.Robinhood,
                balance=total_value,
                tokens=0,  # No GPT tokens used for this sync
                message_bk=None,  # No message associated
                sync_type=SyncType.Robinhood
            )

            logger.info('Portfolio balance synced successfully: $%.2f', total_value)

            return {
                'success': True,
                'data': {
                    'total_portfolio_value': total_value,
                    'balance_captured': balance_record
                }
            }

        except Exception as e:
            logger.error('Error syncing portfolio balance: %s', str(e))
            return {
                'success': False,
                'error': str(e)
            }

    def generate_daily_pulse_html_email(self, analysis, portfolio_summary, market_research):
        """Generate a beautiful HTML email for the daily pulse report."""
        portfolio_profile = portfolio_summary.get('portfolio_profile', {})
        holdings = portfolio_summary.get('holdings', {})
        account_profile = portfolio_summary.get('account_profile', {})
        recent_orders = portfolio_summary.get('recent_orders', [])

        total_equity = portfolio_profile.get('total_equity', '0')
        day_change = portfolio_profile.get('total_return_today', '0')
        buying_power = account_profile.get('buying_power', '0')

        def format_currency(val):
            try:
                return f"${float(val):,.2f}"
            except Exception:
                return val

        html = f"""
        <html>
        <head>
        <style>
            body {{ font-family: Arial, sans-serif; background: #f8f9fa; color: #222; }}
            .container {{ max-width: 700px; margin: 30px auto; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #e0e0e0; padding: 32px; }}
            h1 {{ color: #2a5298; }}
            h2 {{ color: #1e3c72; border-bottom: 1px solid #e0e0e0; padding-bottom: 4px; }}
            .section {{ margin-bottom: 32px; }}
            .holdings-table, .activity-table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
            .holdings-table th, .holdings-table td, .activity-table th, .activity-table td {{ border: 1px solid #e0e0e0; padding: 8px; text-align: left; }}
            .holdings-table th, .activity-table th {{ background: #f0f4fa; }}
            .positive {{ color: #2e8b57; }}
            .negative {{ color: #c0392b; }}
            .market-section {{ background: #f6f8fc; border-radius: 8px; padding: 16px; margin-top: 10px; }}
            .icon-header {{ font-size: 28px; vertical-align: middle; margin-right: 8px; }}
            .divider {{ border-top: 2px solid #e0e0e0; margin: 32px 0; }}
            .highlight {{ background: #eaf6ff; border-left: 4px solid #2a5298; padding: 12px 18px; border-radius: 6px; margin-bottom: 18px; }}
            .footer {{ color: #888; font-size: 13px; margin-top: 40px; text-align: center; }}
        </style>
        </head>
        <body>
        <div class='container'>
            <h1><span class='icon-header'>📈</span>Daily Investment Pulse</h1>
            <div class='section highlight'>
                <h2><span class='icon-header'>💼</span>Portfolio Overview</h2>
                <ul>
                    <li><b>Total Equity:</b> {format_currency(total_equity)}</li>
                    <li><b>Today's Change:</b> {format_currency(day_change)}</li>
                    <li><b>Available Buying Power:</b> {format_currency(buying_power)}</li>
                </ul>
            </div>
            <div class='divider'></div>
            <div class='section'>
                <h2><span class='icon-header'>📊</span>Current Holdings</h2>
                <table class='holdings-table'>
                    <tr>
                        <th>Symbol</th><th>Quantity</th><th>Avg Buy Price</th><th>Current Price</th><th>Total Return</th><th>% Change</th>
                    </tr>
        """
        for symbol, data in holdings.items():
            pct = data.get('percentage', '0')
            try:
                pct_val = float(pct)
                pct_class = 'positive' if pct_val >= 0 else 'negative'
                pct_str = f"<span class='{pct_class}'>{pct_val:.2f}%</span>"
            except Exception:
                pct_str = pct
            html += f"<tr><td>{symbol}</td><td>{data.get('quantity','0')}</td><td>{format_currency(data.get('average_buy_price','0'))}</td><td>{format_currency(data.get('price','0'))}</td><td>{format_currency(data.get('total_return_today_equity','0'))}</td><td>{pct_str}</td></tr>"
        html += """
                </table>
            </div>
            <div class='divider'></div>
            <div class='section'>
                <h2><span class='icon-header'>🔄</span>Recent Trading Activity</h2>
                <table class='activity-table'>
                    <tr><th>Side</th><th>Symbol</th><th>Quantity</th><th>Price</th><th>State</th><th>Date</th></tr>
        """
        for order in recent_orders[:5]:
            symbol = order.get('symbol', 'Unknown')
            if symbol == 'Unknown' and 'instrument' in order:
                instrument_data = order.get('instrument')
                if isinstance(instrument_data, dict):
                    symbol = instrument_data.get('symbol', 'Unknown')
            html += f"<tr><td>{order.get('side','').capitalize()}</td><td>{symbol}</td><td>{order.get('quantity','')}</td><td>{format_currency(order.get('price',''))}</td><td>{order.get('state','')}</td><td>{order.get('created_at','')[:10]}</td></tr>"
        html += """
                </table>
            </div>
            <div class='divider'></div>
            <div class='section market-section'>
                <h2><span class='icon-header'>📰</span>Market Research Summary</h2>
        """
        if market_research.get('market_conditions'):
            html += f"<b>Market Conditions:</b> {market_research['market_conditions']}<br><br>"
        if market_research.get('stock_news'):
            for symbol, summary in market_research['stock_news'].items():
                html += f"<b>{symbol} News:</b> {summary}<br>"
        if market_research.get('sector_analysis'):
            html += f"<b>Sector Analysis:</b> {market_research['sector_analysis']}<br>"
        if market_research.get('search_errors'):
            html += f"<b>Note:</b> {market_research['search_errors']}<br>"
        html += f"""
            </div>
            <div class='divider'></div>
            <div class='section'>
                <h2><span class='icon-header'>🧠</span>Pulse Analysis</h2>
                <div style='white-space: pre-line; font-size: 16px; line-height: 1.6;'>
                    {str(markdown.markdown(analysis))}
                </div>
            </div>
            <div class='footer'>
                Generated by RobinhoodService &middot; {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
            </div>
        </div>
        </body>
        </html>
        """
        return html

    async def send_daily_pulse_email(self, to_email, analysis, portfolio_summary, market_research, subject=None):
        """Generate and send the daily pulse HTML email using the EmailGatewayClient."""
        if not subject:
            subject = f"Your Daily Investment Pulse Report - {datetime.datetime.now().strftime('%Y-%m-%d')}"
        html_body = self.generate_daily_pulse_html_email(analysis, portfolio_summary, market_research)
        await self._email_gateway_client.send_email(
            recipient=to_email,
            subject=subject,
            message=html_body
        )

        await self._email_gateway_client.send_email(
            subject='DEBUG: Pulse Email Prompt Data',
            recipient='dcl525@gmail.com',
            message=f'DEBUG PROMPT INFO: \n{json.dumps(self._prompts, indent=2, ensure_ascii=False)}'
        )
        self._prompts = {}  # Clear prompts after sending
        logger.info(f"Daily pulse email sent to {to_email}")
