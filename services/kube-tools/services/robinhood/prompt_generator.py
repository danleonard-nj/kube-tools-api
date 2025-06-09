from framework.logger import get_logger
from models.robinhood_models import Article, PortfolioData, MarketResearch, TruthSocialPost

logger = get_logger(__name__)


def generate_truth_post_single_post_analysis_prompt(post: TruthSocialPost) -> str:
    return f"""
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


def generate_trut_social_market_implication_analysis_prompt(all_content: str) -> str:
    return f"""
    Analyze the overall sentiment of these presidential communications for financial market implications.

    Content to analyze:
    {all_content[:5000]}  # Limit content to avoid token limits

    Provide sentiment breakdown as percentages that sum to 100%.

    Respond ONLY in valid JSON format:
    {{
        "scores": {{
            "positive": 0.0-1.0,
            "negative": 0.0-1.0, 
            "neutral": 0.0-1.0
        }},
        "dominant": "positive|negative|neutral",
        "market_themes": ["theme1", "theme2", "theme3"],
        "confidence": 0.0-1.0
    }}
    """


def generate_filter_article_prompt(snippet: str, type_label: str) -> str:
    """Generate prompt for filtering articles based on content."""
    return f"""
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


def generate_article_chunk_summary_prompt(chunk: list[Article], type_label: str) -> str:
    prompt_lines = [
        f"Summarize the following {type_label} articles in a concise, clear paragraph. "
        "Highlight key trends and sentiment. Ignore marketing/advertising content.\n"
    ]

    for i, article in enumerate(chunk, 1):
        prompt_lines.append(article.to_prompt_block(i))
        prompt_lines.append("")

    return "\n".join(prompt_lines)


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
        day_change = portfolio_profile.total_day_change

        # if portfolio_profile.adjusted_equity_previous_close and portfolio_profile.market_value:
        #     try:
        #         prev = float(portfolio_profile.adjusted_equity_previous_close)
        #         curr = float(portfolio_profile.market_value)
        #         day_change = curr - prev
        #     except Exception:
        #         day_change = None
        # if day_change is None:
        #     day_change = portfolio_profile.total_return_today or '0'

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
