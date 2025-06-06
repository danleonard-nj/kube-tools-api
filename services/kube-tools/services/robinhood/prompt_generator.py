from framework.logger import get_logger
from models.robinhood_models import PortfolioData, MarketResearch

logger = get_logger(__name__)


class PromptGenerator:
    def __init__(
        self
    ):
        self._count = 0

    def _passthrough_save_prompt(self, prompt: str) -> str:
        """
        Save the prompt to a file or database for future reference.
        This is a placeholder for actual implementation.
        # """
        # # Here you would implement the logic to save the prompt
        # # For now, we just log it
        # logger.info(f"Saving prompt: {prompt}")
        # with open(f'./prompts/prompt_{self._count}.txt', 'w') as f:
        #     f.write(prompt)
        # self._count += 1
        return prompt

    """Class for generating prompts for GPT models"""

    def compile_daily_pulse_prompt(self, portfolio_data: PortfolioData, summarized_market_research: MarketResearch = None) -> str:
        """
        Compile prompt for daily pulse analysis

        Args:
            portfolio_data: Portfolio data from Robinhood
            summarized_market_research: Summarized market research

        Returns:
            Formatted prompt string
        """
        # Extract key metrics
        portfolio_profile = portfolio_data.portfolio_profile
        holdings = portfolio_data.holdings
        account_profile = portfolio_data.account_profile
        recent_orders = portfolio_data.recent_orders

        # Calculate key metrics
        total_equity = portfolio_profile.market_value or portfolio_profile.equity or '0'
        day_change = None
        if portfolio_profile.equity_previous_close and portfolio_profile.market_value:
            try:
                prev = float(portfolio_profile.equity_previous_close)
                curr = float(portfolio_profile.market_value)
                day_change = curr - prev
            except Exception:
                day_change = None
        if day_change is None:
            day_change = portfolio_profile.total_return_today or '0'
        buying_power = account_profile.buying_power or '0'

        # Format holdings information
        holdings_summary = []
        for symbol, data in holdings.items():
            holdings_summary.append({
                'symbol': symbol,
                'quantity': data.quantity or '0',
                'average_buy_price': data.average_buy_price or '0',
                'current_price': data.price or '0',
                'total_return': data.equity_change or '0',
                # Use intraday percent change
                'percentage_change': data.intraday_percent_change
                # 'percentage_change': data.percentage or data.percent_change or '0'
            })

        # Format recent orders
        recent_activity = []
        for order in recent_orders[:5]:  # Top 5 recent orders
            # Extract symbol from instrument URL or dict if needed
            symbol = order.symbol or 'Unknown'
            if symbol == 'Unknown' and order.instrument:
                instrument_data = order.instrument
                if isinstance(instrument_data, dict):
                    symbol = instrument_data.symbol or 'Unknown'
                elif isinstance(instrument_data, str):
                    # Try to extract symbol from instrument URL string
                    symbol = instrument_data.split('/')[-2] if '/' in instrument_data else instrument_data

            recent_activity.append({
                'instrument_symbol': symbol,
                'side': order.side or 'Unknown',
                'quantity': order.quantity or '0',
                'price': order.price or '0',
                'state': order.state or 'Unknown',
                'created_at': order.created_at or ''
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
            if summarized_market_research.market_conditions:
                prompt += f"Market Conditions: {summarized_market_research.market_conditions}\n"
            if summarized_market_research.stock_news:
                for symbol, summary in summarized_market_research.stock_news.items():
                    prompt += f"{symbol} News: {summary}\n"
            if summarized_market_research.sector_analysis:
                prompt += f"Sector Analysis: {summarized_market_research.sector_analysis}\n"
            if summarized_market_research.search_errors:
                prompt += f"Note: {summarized_market_research.search_errors}\n"
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

        return self._passthrough_save_prompt(prompt)

    async def compile_daily_pulse_prompt_with_symbols(
            self, portfolio_data: PortfolioData,
            summarized_market_research: MarketResearch = None,
            order_symbol_map: dict = None) -> str:
        """
        Like compile_daily_pulse_prompt, but takes a mapping of order instrument URLs to symbols for accurate display.

        Args:
            portfolio_data: Portfolio data from Robinhood
            summarized_market_research: Summarized market research
            order_symbol_map: Mapping of order instrument URLs to symbols

        Returns:
            Formatted prompt string
        """
        # Extract key metrics
        portfolio_profile = portfolio_data.portfolio_profile
        holdings = portfolio_data.holdings
        account_profile = portfolio_data.account_profile
        recent_orders = portfolio_data.recent_orders

        # Calculate key metrics
        total_equity = portfolio_profile.market_value or portfolio_profile.equity or '0'
        day_change = None
        if portfolio_profile.equity_previous_close and portfolio_profile.market_value:
            try:
                prev = float(portfolio_profile.equity_previous_close)
                curr = float(portfolio_profile.market_value)
                day_change = curr - prev
            except Exception:
                day_change = None
        if day_change is None:
            day_change = portfolio_profile.total_return_today or '0'
        buying_power = account_profile.buying_power or '0'

        # Format holdings information
        holdings_summary = []
        for symbol, data in holdings.items():
            holdings_summary.append({
                'symbol': symbol,
                'quantity': data.quantity or '0',
                'average_buy_price': data.average_buy_price or '0',
                'current_price': data.price or '0',
                'total_return': data.equity_change or '0',
                'percentage_change': data.percentage or data.percent_change or '0'
            })

        # Format recent orders (now 15)
        recent_activity = []
        for order in recent_orders[:15]:
            symbol = None
            instrument_url = None
            if hasattr(order, 'symbol') and order.symbol:
                symbol = order.symbol
            elif hasattr(order, 'instrument') and order.instrument:
                instrument_url = order.instrument if isinstance(order.instrument, str) else getattr(order.instrument, 'url', None)
            if not symbol and instrument_url and order_symbol_map:
                symbol = order_symbol_map.get(instrument_url, 'Unknown')
            elif symbol == 'Unknown' and instrument_url and order_symbol_map:
                symbol = order_symbol_map.get(instrument_url, 'Unknown')
            recent_activity.append({
                'instrument_symbol': symbol,
                'side': getattr(order, 'side', 'Unknown'),
                'quantity': getattr(order, 'quantity', '0'),
                'price': getattr(order, 'price', '0'),
                'state': getattr(order, 'state', 'Unknown'),
                'created_at': getattr(order, 'created_at', '')
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
            if summarized_market_research.market_conditions:
                prompt += f"Market Conditions: {summarized_market_research.market_conditions}\n"
            if summarized_market_research.stock_news:
                for symbol, summary in summarized_market_research.stock_news.items():
                    prompt += f"{symbol} News: {summary}\n"
            if summarized_market_research.sector_analysis:
                prompt += f"Sector Analysis: {summarized_market_research.sector_analysis}\n"
            if summarized_market_research.search_errors:
                prompt += f"Note: {summarized_market_research.search_errors}\n"
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

        return self._passthrough_save_prompt(prompt)

    def generate_trade_outlook_prompt(self, trade: dict, news_summary: str = None, sector_summary: str = None) -> str:
        """
        Generate a prompt for individual trade outlook analysis
        """
        pct_str = f"{trade['pct']:.2f}%" if trade['pct'] is not None else "N/A"

        trade_prompt = (
            f"Trade details: Side: {trade['side']}, Symbol: {trade['symbol']}, Quantity: {trade['quantity']}, "
            f"Trade Price: {trade['trade_price']}, Current Price: {trade['current_price']}, "
            f"Gain: {trade['gain']}, Percent: {pct_str}. "
        )

        if news_summary:
            trade_prompt += f"\nRecent news for {trade['symbol']}: {news_summary}\n"

        if sector_summary:
            trade_prompt += f"\nSector context: {sector_summary}\n"

        trade_prompt += "Write a short, 1 sentence outlook or opinion for this trade."

        return self._passthrough_save_prompt(trade_prompt)

    def generate_trade_outlook_summary_prompt(self, trade_rows: list, trade_stats: dict) -> str:
        """
        Generate a prompt for overall trade performance summary

        Args:
            trade_rows: List of trade data dictionaries
            trade_stats: Statistics dictionary with keys like 'total_gain', 'total_loss', etc.

        Returns:
            Formatted prompt string for trade summary
        """
        trade_outlook_prompt = (
            f"Here is a table of recent trades (side, symbol, quantity, price, gain/loss):\n"
            f"{trade_rows}\n"
            f"Total gain: {trade_stats['total_gain']:.2f}, Total loss: {trade_stats['total_loss']:.2f}, "
            f"Wins: {trade_stats['win_count']}, Losses: {trade_stats['loss_count']}. "
            f"Write a short, natural language summary and outlook for these trades."
        )

        return self._passthrough_save_prompt(trade_outlook_prompt)

    def generate_sector_analysis_summary_prompt(self, valuable_articles: list) -> str:
        """
        Generate a prompt for summarizing sector analysis articles in a structured markdown format.
        Args:
            valuable_articles: List of Article objects or dicts with sector analysis content.
        Returns:
            Formatted prompt string for sector analysis summary.
        """
        prompt_lines = [
            "Summarize the following sector analysis articles in a structured markdown format. "
            "Start with the header '### Sector Analysis Summary' followed by dedicated sections for each major sector. "
            "Use markdown headers like '**Technology Sector**', '**Healthcare Sector**', '**Financial Services Sector**', and '**Energy Sector**' for each section. "
            "Provide 2-3 concise sentences for each sector covering key trends, major companies, and performance indicators. "
            "End with a brief concluding sentence about sector dynamics and growth opportunities.\n"
        ]
        for i, article in enumerate(valuable_articles, 1):
            if hasattr(article, 'to_prompt_block'):
                prompt_lines.append(article.to_prompt_block(i))
            else:
                # fallback for dict-like articles
                prompt_lines.append(getattr(type(article), 'dict_to_prompt_block', lambda a, idx: str(a))(article, i))
            prompt_lines.append("")
        prompt = "\n".join(prompt_lines)
        return self._passthrough_save_prompt(prompt)
