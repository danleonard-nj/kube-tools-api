import datetime
import markdown
import json
import html
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from framework.logger import get_logger
from models.robinhood_models import MarketResearch, MarketResearchSummary, PortfolioData, DebugReport, SectionTitle, SummarySection

if TYPE_CHECKING:
    from models.robinhood_models import TruthSocialInsights

logger = get_logger(__name__)


class EmailGenerator:
    """Class for generating HTML emails for various reports"""

    # Configuration constants
    MAX_RECENT_ORDERS = 15
    DEFAULT_CURRENCY_FORMAT = "${:,.2f}"

    def __init__(self):
        """Initialize the email generator with default styling."""
        self._css_styles = self._get_default_css_styles()

    def _get_default_css_styles(self) -> str:
        """Get the default CSS styles for emails with enhanced table styling."""
        return """
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                background: #f8f9fa; 
                color: #222; 
                margin: 0; 
                padding: 0; 
            }
            .container { 
                max-width: 800px; 
                margin: 30px auto; 
                background: #fff; 
                border-radius: 12px; 
                box-shadow: 0 4px 20px rgba(0,0,0,0.08); 
                padding: 40px; 
            }
            h1 { 
                color: #2a5298; 
                font-size: 28px; 
                margin-bottom: 8px; 
            }
            h2 { 
                color: #1e3c72; 
                border-bottom: 2px solid #e0e6ed; 
                padding-bottom: 8px; 
                font-size: 20px; 
                margin-top: 32px; 
                margin-bottom: 16px; 
            }
            h3 { 
                color: #2a5298; 
                font-size: 16px; 
                margin-top: 24px; 
                margin-bottom: 12px; 
            }
            .section { 
                margin-bottom: 32px; 
            }
            
            /* Enhanced table styles */
            .holdings-table, .activity-table, .trade-performance-table { 
                width: 100%; 
                border-collapse: collapse; 
                margin-top: 16px; 
                background: white;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            }
            
            .holdings-table th, .activity-table th, .trade-performance-table th { 
                background: linear-gradient(135deg, #2a5298 0%, #1e3c72 100%); 
                color: white;
                padding: 14px 12px;
                text-align: left;
                font-weight: 600;
                font-size: 14px;
                letter-spacing: 0.5px;
                border: none;
            }
            
            .holdings-table td, .activity-table td, .trade-performance-table td { 
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #f1f3f4;
                font-size: 14px;
                vertical-align: middle;
            }
            
            .holdings-table tbody tr:hover, 
            .activity-table tbody tr:hover, 
            .trade-performance-table tbody tr:hover { 
                background-color: #f8f9ff;
            }
            
            .holdings-table tbody tr:last-child td,
            .activity-table tbody tr:last-child td,
            .trade-performance-table tbody tr:last-child td {
                border-bottom: none;
            }

            /* Alternating row colors for better readability */
            .holdings-table tbody tr:nth-child(even),
            .activity-table tbody tr:nth-child(even),
            .trade-performance-table tbody tr:nth-child(even) {
                background-color: #fafbfc;
            }
            
            /* Color coding for positive/negative values */
            .positive { 
                color: #0d7833; 
                font-weight: 600;
            }
            .negative { 
                color: #d73e2a; 
                font-weight: 600;
            }
            
            /* Enhanced section styling */
            .market-section { 
                background: linear-gradient(135deg, #f6f8fc 0%, #e8f0fe 100%); 
                border-radius: 10px; 
                padding: 20px; 
                margin-top: 16px; 
                border-left: 4px solid #2a5298;
            }
            
            .pipeline-section { 
                background: #ffffff; 
                border-radius: 10px; 
                padding: 20px; 
                margin-top: 16px; 
                border: 1px solid #e8eaed;
                box-shadow: 0 1px 3px rgba(0,0,0,0.04);
            }
            
            .icon-header { 
                font-size: 24px; 
                vertical-align: middle; 
                margin-right: 10px; 
            }
            
            .divider { 
                border-top: 2px solid #e8eaed; 
                margin: 40px 0; 
            }
            
            .highlight { 
                background: linear-gradient(135deg, #eaf6ff 0%, #d6efff 100%); 
                border-left: 4px solid #2a5298; 
                padding: 16px 24px; 
                border-radius: 8px; 
                margin-bottom: 24px; 
                box-shadow: 0 2px 8px rgba(42, 82, 152, 0.08);
            }
            
            .footer { 
                color: #5f6368; 
                font-size: 13px; 
                margin-top: 48px; 
                text-align: center; 
                padding-top: 24px;
                border-top: 1px solid #e8eaed;
            }
            
            .pipeline-table { 
                font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace; 
                font-size: 12px; 
                white-space: pre-line; 
                background: #f8f9fa; 
                padding: 16px; 
                border-radius: 6px; 
                overflow-x: auto; 
                border: 1px solid #e8eaed;
            }

            /* Performance metrics grid styling */
            .metrics-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 16px;
                margin-top: 16px;
            }

            .metric-card {
                background: linear-gradient(135deg, #f6f8fc 0%, #e8f0fe 100%);
                padding: 16px;
                border-radius: 8px;
                border-left: 4px solid #2a5298;
                box-shadow: 0 2px 4px rgba(0,0,0,0.04);
            }

            .metric-label {
                font-weight: 600;
                color: #2a5298;
                font-size: 13px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-bottom: 4px;
            }

            .metric-value {
                font-size: 20px;
                font-weight: 700;
                color: #1a1a1a;
            }

            /* Responsive design for mobile */
            @media only screen and (max-width: 600px) {
                .container {
                    margin: 16px;
                    padding: 24px;
                }
                
                .holdings-table, .activity-table, .trade-performance-table {
                    font-size: 12px;
                }
                
                .holdings-table th, .activity-table th, .trade-performance-table th {
                    padding: 10px 8px;
                    font-size: 12px;
                }
                
                .holdings-table td, .activity-table td, .trade-performance-table td {
                    padding: 8px 6px;
                    font-size: 12px;
                }
                
                .metrics-grid {
                    grid-template-columns: 1fr;
                }
            }
        """

    def _safe_format_currency(self, value: Any) -> str:
        """Safely format a value as currency."""
        try:
            if value is None:
                return "-"
            return self.DEFAULT_CURRENCY_FORMAT.format(float(value))
        except (ValueError, TypeError):
            logger.warning(f"Failed to format currency value: {value}")
            return str(value) if value is not None else "-"

    def _generate_portfolio_holdings_section(self, portfolio_data: Dict[str, Any]) -> str:
        """Generate portfolio holdings section with proper HTML table."""
        if not portfolio_data or isinstance(portfolio_data, str):
            # Handle legacy text format or errors
            return f"""
                <div class='section pipeline-section'>
                    <h2><span class='icon-header'>💼</span>Portfolio Holdings</h2>
                    <div class='pipeline-table'>{html.escape(str(portfolio_data))}</div>
                </div>
            """

        holdings = portfolio_data.get('holdings', [])
        total_value = portfolio_data.get('total_value', 0)

        if not holdings:
            return f"""
                <div class='section pipeline-section'>
                    <h2><span class='icon-header'>💼</span>Portfolio Holdings</h2>
                    <p>No portfolio holdings data available</p>
                </div>
            """

        # Generate HTML table
        table_rows = []
        for holding in holdings:
            symbol = html.escape(str(holding.get('symbol', 'N/A')))
            shares = holding.get('shares', 0)
            current_price = holding.get('current_price', 0)
            market_value = holding.get('market_value', 0)
            cost_basis = holding.get('cost_basis', 0)
            unrealized_pnl = holding.get('unrealized_pnl', 0)
            pnl_percent = holding.get('pnl_percent', 0)

            # Color-code P&L
            pnl_class = 'positive' if unrealized_pnl > 0 else 'negative' if unrealized_pnl < 0 else ''
            pnl_sign = '+' if unrealized_pnl > 0 else ''

            table_rows.append(f"""
                <tr>
                    <td><strong>{symbol}</strong></td>
                    <td>{shares:.2f}</td>
                    <td>{self._safe_format_currency(current_price)}</td>
                    <td>{self._safe_format_currency(market_value)}</td>
                    <td>{self._safe_format_currency(cost_basis)}</td>
                    <td class='{pnl_class}'>{pnl_sign}{self._safe_format_currency(abs(unrealized_pnl))}</td>
                    <td class='{pnl_class}'>{pnl_sign}{pnl_percent:.1f}%</td>
                </tr>
            """)

        table_html = f"""
            <table class='holdings-table'>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Shares</th>
                        <th>Current Price</th>
                        <th>Market Value</th>
                        <th>Cost Basis</th>
                        <th>Unrealized P&L</th>
                        <th>P&L %</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(table_rows)}
                    <tr style='border-top: 2px solid #2a5298; font-weight: bold;'>
                        <td><strong>TOTAL</strong></td>
                        <td>-</td>
                        <td>-</td>
                        <td><strong>{self._safe_format_currency(total_value)}</strong></td>
                        <td>-</td>
                        <td>-</td>
                        <td>-</td>
                    </tr>
                </tbody>
            </table>
        """

        return f"""
            <div class='section pipeline-section'>
                <h2><span class='icon-header'>💼</span>Portfolio Holdings</h2>
                {table_html}
            </div>
        """

    def _generate_trading_activity_section(self, trading_data: Dict[str, Any]) -> str:
        """Generate trading activity section with proper HTML tables."""
        if not trading_data or isinstance(trading_data, str):
            # Handle legacy text format or errors
            return f"""
                <div class='section pipeline-section'>
                    <h2><span class='icon-header'>📊</span>Trading Activity & Performance</h2>
                    <div class='pipeline-table'>{html.escape(str(trading_data))}</div>
                </div>
            """

        recent_trades = trading_data.get('recent_trades', [])
        performance_metrics = trading_data.get('performance_metrics', {})

        # Recent trades table
        trades_html = ""
        if recent_trades:
            trade_rows = []
            for trade in recent_trades:
                date = html.escape(str(trade.get('date', 'N/A')))
                action = html.escape(str(trade.get('action', 'N/A')))
                symbol = html.escape(str(trade.get('symbol', 'N/A')))
                shares = trade.get('shares', 0)
                price = trade.get('price', 0)
                value = trade.get('value', 0)

                trade_rows.append(f"""
                    <tr>
                        <td>{date}</td>
                        <td><span class='{"positive" if action.upper() == "BUY" else "negative"}'>{action.upper()}</span></td>
                        <td><strong>{symbol}</strong></td>
                        <td>{shares:.2f}</td>
                        <td>{self._safe_format_currency(price)}</td>
                        <td>{self._safe_format_currency(value)}</td>
                    </tr>
                """)

            trades_html = f"""
                <h3>Recent Trading Activity</h3>
                <table class='activity-table'>
                    <thead>
                        <tr>
                            <th>Date</th>
                            <th>Action</th>
                            <th>Symbol</th>
                            <th>Shares</th>
                            <th>Price</th>
                            <th>Value</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(trade_rows)}
                    </tbody>
                </table>
            """
        else:
            trades_html = "<h3>Recent Trading Activity</h3><p>No recent trading activity found.</p>"

        # Performance metrics using enhanced grid layout
        metrics_html = f"""
            <h3>Performance Metrics</h3>
            <div class='metrics-grid'>
                <div class='metric-card'>
                    <div class='metric-label'>Total Return</div>
                    <div class='metric-value'>{self._safe_format_currency(performance_metrics.get('total_return', 0))}</div>
                </div>
                <div class='metric-card'>
                    <div class='metric-label'>Day Change</div>
                    <div class='metric-value'>{self._safe_format_currency(performance_metrics.get('day_change', 0))}</div>
                </div>
                <div class='metric-card'>
                    <div class='metric-label'>Week Change</div>
                    <div class='metric-value'>{self._safe_format_currency(performance_metrics.get('week_change', 0))}</div>
                </div>
                <div class='metric-card'>
                    <div class='metric-label'>Month Change</div>
                    <div class='metric-value'>{self._safe_format_currency(performance_metrics.get('month_change', 0))}</div>
                </div>
            </div>
        """

        return f"""
            <div class='section pipeline-section'>
                <h2><span class='icon-header'>📊</span>Trading Activity & Performance</h2>
                {trades_html}
                <div style='margin-top: 24px;'>
                    {metrics_html}
                </div>
            </div>
        """

    def _generate_pipeline_summary_sections(self, summary_sections: List[SummarySection], icon: str = "📊") -> str:
        """Generate HTML from pipeline-processed summary sections (updated to handle structured data)."""
        if not summary_sections:
            return ""

        presidential_sections = [
            SectionTitle.PRESIDENTIAL_INTELLIGENCE_BRIEF,
            SectionTitle.TOP_IMPACT_POSTS,
            SectionTitle.MARKET_IMPACT_POLICY_ANALYSIS,
            SectionTitle.TRADING_STRATEGY_IMPLICATIONS
        ]

        html_parts = []
        for section in summary_sections:
            title = html.escape(str(section.title))
            snippet = section.snippet

            # Check if this is structured portfolio data
            if section.title == SectionTitle.PORTFOLIO_SUMMARY and isinstance(snippet, dict):
                html_parts.append(self._generate_portfolio_holdings_section(snippet))
                continue

            # TODO: SKIPPING THIS SECTION IT'S A DUPLICATE
            # TODO: Remove any code that generates this section
            if section.title == SectionTitle.TRADING_SUMMARY_AND_PERFORMANCE and isinstance(snippet, dict):
                # html_parts.append(self._generate_trading_activity_section(snippet))
                continue

            if section.title in presidential_sections:
                logger.info(f'Appending raw HTML for section: {title}')
                html_parts.append(snippet)
                continue

            # Handle string/text content (existing logic)
            snippet_str = str(snippet)

            def is_table_like(text):
                lines = text.strip().splitlines()
                if len(lines) < 2:
                    return False
                table_lines = [l for l in lines if ("  " in l or "\t" in l)]
                return len(table_lines) >= max(2, len(lines) // 2)

            def try_render_html_table(text):
                logger.info(f'Attempting to render HTML table for section: {section.title}')
                lines = [l for l in text.strip().splitlines() if l.strip()]
                if len(lines) < 2:
                    return None
                import re
                header = re.split(r"\s{2,}|\t", lines[0].strip())
                rows = [re.split(r"\s{2,}|\t", l.strip()) for l in lines[1:]]
                if not all(len(r) == len(header) for r in rows):
                    return None
                ths = ''.join(f"<th>{html.escape(h)}</th>" for h in header)
                trs = ''.join('<tr>' + ''.join(f"<td>{html.escape(cell)}</td>" for cell in row) + '</tr>' for row in rows)
                return f"<table class='pipeline-table'><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>"

            # Improved table-like detection and rendering
            html_table = try_render_html_table(snippet_str) if is_table_like(snippet_str) else None
            if html_table:
                html_parts.append(f"""
                    <div class='section pipeline-section'>
                        <h2><span class='icon-header'>{icon}</span>{title}</h2>
                        {html_table}
                    </div>
                """)
            elif is_table_like(snippet_str):
                # Fallback: render as monospace if table-like but not convertible
                html_parts.append(f"""
                    <div class='section pipeline-section'>
                        <h2><span class='icon-header'>{icon}</span>{title}</h2>
                        <div class='pipeline-table'>{html.escape(snippet_str)}</div>
                    </div>
                """)
            elif "Recent Trading Activity:" in snippet_str and "Performance Metrics:" in snippet_str:
                # This looks like the trading summary - render as monospace
                html_parts.append(f"""
                    <div class='section pipeline-section'>
                        <h2><span class='icon-header'>{icon}</span>{title}</h2>
                        <div class='pipeline-table'>{html.escape(snippet_str)}</div>
                    </div>
                """)
            else:
                # Regular formatted text
                try:
                    formatted_snippet = markdown.markdown(snippet_str) if snippet_str else ""
                except Exception as e:
                    logger.warning(f"Failed to format markdown for summary section: {e}")
                    formatted_snippet = html.escape(snippet_str)

                html_parts.append(f"""
                    <div class='section pipeline-section'>
                        <h2><span class='icon-header'>{icon}</span>{title}</h2>
                        <div>{formatted_snippet}</div>
                    </div>
                """)

        return "".join(html_parts)

    def _generate_portfolio_overview_section(self, portfolio_data: PortfolioData) -> str:
        """Generate the portfolio overview section HTML."""
        portfolio_profile = portfolio_data.portfolio_profile
        account_profile = portfolio_data.account_profile

        # Extract values with fallbacks
        total_equity = (
            portfolio_profile.equity or
            portfolio_profile.market_value or
            '0'
        )
        day_change = (
            getattr(portfolio_profile, 'total_return_today', None) or
            getattr(portfolio_profile, 'day_over_day_change', None) or
            '0'
        )
        buying_power = account_profile.buying_power or '0'

        return f"""
            <div class='section highlight'>
                <h2><span class='icon-header'>💼</span>Portfolio Overview</h2>
                <ul>
                    <li><b>Total Equity:</b> {self._safe_format_currency(total_equity)}</li>
                    <li><b>Today's Change:</b> {self._safe_format_currency(day_change)}</li>
                    <li><b>Available Buying Power:</b> {self._safe_format_currency(buying_power)}</li>
                </ul>
            </div>
        """

    def _format_trade_result(self, trade_row: Dict[str, Any]) -> str:
        """Format trade result with appropriate styling."""
        gain = trade_row.get('gain')
        pct = trade_row.get('pct')
        result_status = trade_row.get('result_status')

        if not all([gain is not None, pct is not None, result_status]):
            return "-"

        try:
            if result_status == 'up':
                return f"<span class='positive'>+{gain:.2f} ({pct:.2f}%)</span>"
            elif result_status == 'down':
                return f"<span class='negative'>{gain:.2f} ({pct:.2f}%)</span>"
            elif result_status == 'even':
                return f"<span style='color:#888;'>0.00 (0.00%)</span>"
            else:
                return "-"
        except (ValueError, TypeError):
            logger.warning(f"Failed to format trade result: {trade_row}")
            return "-"

    def _generate_trade_performance_section(self, trade_performance: Optional[List[Dict[str, Any]]]) -> str:
        """Generate the trade performance section HTML."""
        if not trade_performance:
            return ""

        html_parts = [
            """
            <div class='section'>
                <h2><span class='icon-header'>🔎</span>Recent Trade Performance & Outlook</h2>
                <table class='trade-performance-table'>
                    <tr><th>Side</th><th>Symbol</th><th>Trade Price</th><th>Current Price</th><th>Result</th><th>Outlook</th></tr>
            """
        ]

        for row in trade_performance:
            side = html.escape(str(row.get('side', '-')))
            symbol = html.escape(str(row.get('symbol', '-')))
            trade_price = self._safe_format_currency(row.get('trade_price'))
            current_price = self._safe_format_currency(row.get('current_price'))
            result_str = self._format_trade_result(row)
            outlook = html.escape(str(row.get('outlook', '')))

            html_parts.append(
                f"<tr>"
                f"<td>{side}</td>"
                f"<td>{symbol}</td>"
                f"<td>{trade_price}</td>"
                f"<td>{current_price}</td>"
                f"<td>{result_str}</td>"
                f"<td style='font-size:13px;color:#333;'>{outlook}</td>"
                f"</tr>"
            )

        html_parts.append("</table></div>")
        return "".join(html_parts)

    def _generate_trade_outlook_section(self, trade_outlook: Optional[str]) -> str:
        """Generate the trade outlook section HTML."""
        if not trade_outlook:
            return ""

        return f"""
            <div class='section'>
                <h2><span class='icon-header'>🔮</span>Trade Outlook</h2>
                <div style='font-size: 16px; line-height: 1.6; background: #f9f9f9; padding: 16px; border-radius: 8px; border-left: 4px solid #2a5298;'>
                    {html.escape(trade_outlook)}
                </div>
            </div>
        """

    def _generate_pulse_analysis_section(self, analysis: str) -> str:
        """Generate the pulse analysis section HTML."""
        try:
            formatted_analysis = markdown.markdown(str(analysis))
        except Exception as e:
            logger.warning(f"Failed to format markdown for analysis: {e}")
            formatted_analysis = html.escape(str(analysis))

        return f"""
            <div class='section'>
                <h2><span class='icon-header'>🧠</span>Pulse Analysis</h2>
                <div style='white-space: pre-line; font-size: 16px; line-height: 1.6;'>
                    {formatted_analysis}
                </div>
            </div>
        """

    def generate_daily_pulse_html_email(
        self,
        analysis: str,
        portfolio_data: PortfolioData,
        market_research_summary: MarketResearchSummary,
        trade_performance: Optional[List[Dict[str, Any]]] = None,
        trade_outlook: Optional[str] = None
    ) -> str:
        """
        Generate a beautiful HTML email using pipeline-processed summaries.

        Args:
            analysis: Analysis text generated by GPT
            portfolio_data: PortfolioData for overview section
            market_research_summary: MarketResearchSummary with processed summaries
            trade_performance: Optional list of trade performance data
            trade_outlook: Optional trade outlook text

        Returns:
            HTML string for the email
        """
        try:
            # Generate all sections
            portfolio_overview_section = self._generate_portfolio_overview_section(portfolio_data)

            # Use pipeline-processed portfolio holdings table
            portfolio_holdings_section = self._generate_pipeline_summary_sections(
                market_research_summary.portfolio_summary, "💼"
            ) if market_research_summary.portfolio_summary else ""

            # Use pipeline-processed combined trading summary (activity + performance already combined)
            trading_section = self._generate_pipeline_summary_sections(
                market_research_summary.trading_summary, "📊"
            ) if market_research_summary.trading_summary else ""

            trade_performance_section = self._generate_trade_performance_section(trade_performance)

            trade_outlook_section = self._generate_trade_outlook_section(trade_outlook)

            # Use pipeline-processed market research sections
            market_conditions_section = self._generate_pipeline_summary_sections(
                market_research_summary.market_conditions, "📰"
            ) if market_research_summary.market_conditions else ""

            # Stock news summaries
            stock_news_sections = ""
            if market_research_summary.stock_news:
                for symbol, sections in market_research_summary.stock_news.items():
                    if sections:
                        stock_news_sections += self._generate_pipeline_summary_sections(
                            sections, "📈"
                        )

            # Sector analysis summary
            sector_analysis_section = self._generate_pipeline_summary_sections(
                market_research_summary.sector_analysis, "🏭"
            ) if market_research_summary.sector_analysis else ""

            # Use pipeline-processed Truth Social analysis
            truth_social_section = self._generate_pipeline_summary_sections(
                market_research_summary.truth_social_summary, "🏛️"
            ) if market_research_summary.truth_social_summary else ""

            analysis_section = self._generate_pulse_analysis_section(analysis)

            # Combine into full HTML with ALL sections
            html = f"""
            <html>
            <head>
            <style>
                {self._css_styles}
            </style>
            </head>
            <body>
            <div class='container'>
                <h1><span class='icon-header'>📈</span>Daily Investment Pulse</h1>
                {portfolio_overview_section}
                <div class='divider'></div>
                {portfolio_holdings_section}
                <div class='divider'></div>
                {trading_section}
                {"<div class='divider'></div>" + trade_performance_section if trade_performance_section else ""}
                {"<div class='divider'></div>" + trade_outlook_section if trade_outlook_section else ""}
                <div class='divider'></div>
                {market_conditions_section}
                {stock_news_sections}
                {sector_analysis_section}
                {"<div class='divider'></div>" + truth_social_section if truth_social_section else ""}
                <div class='divider'></div>
                {analysis_section}
                <div class='footer'>
                    Generated by RobinhoodService Pipeline &middot; {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
                </div>
            </div>
            </body>
            </html>
            """

            return html

        except Exception as e:
            logger.error(f"Failed to generate daily pulse email: {e}", exc_info=True)
            # Return a minimal fallback email
            return self._generate_fallback_email(str(e))

    def _generate_fallback_email(self, error_message: str) -> str:
        """Generate a fallback email when the main generation fails."""
        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #222;">
            <div style="max-width: 600px; margin: 30px auto; padding: 20px; background: #fff; border: 1px solid #ddd;">
                <h1 style="color: #c0392b;">📧 Email Generation Error</h1>
                <p>Sorry, there was an error generating your daily pulse report:</p>
                <p style="background: #f8f9fa; padding: 10px; border-radius: 4px; font-family: monospace;">
                    {html.escape(error_message)}
                </p>
                <p>Please check the logs for more details.</p>
                <p style="color: #888; font-size: 12px;">
                    Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
                </p>
            </div>
        </body>
        </html>
        """

    def generate_daily_pulse_subject(self, custom_subject: Optional[str] = None) -> str:
        """
        Generate a subject line for the daily pulse email.

        Args:
            custom_subject: Optional custom subject line

        Returns:
            Subject string
        """
        if custom_subject:
            return str(custom_subject)

        return f"Your Daily Investment Pulse Report - {datetime.datetime.now().strftime('%Y-%m-%d')}"

    def generate_admin_debug_html_report(self, debug_report: DebugReport, stats: Optional[Dict[str, Any]] = None) -> str:
        """
        Generate a clean, formatted HTML admin debug report with cache stats, 
        search counts, GPT token usage, article/source links, and all relevant metadata.

        Args:
            debug_report: Debug report data
            stats: Optional statistics dictionary

        Returns:
            HTML string for the debug report
        """
        try:
            dr = debug_report
            stats = stats or {}

            def safe_escape(val: Any) -> str:
                """Safely escape HTML characters."""
                return html.escape(str(val)) if val is not None else ''

            # Generate sections
            header_section = self._generate_debug_header_section(dr, stats, safe_escape)
            stats_section = self._generate_debug_stats_section(stats, safe_escape)
            links_section = self._generate_debug_links_section(dr, safe_escape)
            prompts_section = self._generate_debug_prompts_section(dr, safe_escape)
            data_section = self._generate_debug_data_section(dr, safe_escape)

            html_out = f"""
            <html>
            <head>
            <style>
                body {{ font-family: Arial, sans-serif; background: #f8f9fa; color: #222; }}
                .container {{ max-width: 900px; margin: 30px auto; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #e0e0e0; padding: 32px; }}
                h1, h2, h3 {{ color: #2a5298; }}
                .section {{ margin-bottom: 32px; }}
                .table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                .table th, .table td {{ border: 1px solid #e0e0e0; padding: 8px; text-align: left; }}
                .table th {{ background: #f0f4fa; }}
                .divider {{ border-top: 2px solid #e0e0e0; margin: 32px 0; }}
                .small {{ color: #888; font-size: 13px; }}
                .link-list li {{ margin-bottom: 4px; }}
                pre {{ white-space: pre-wrap; background: #f6f8fc; padding: 8px; border-radius: 6px; overflow-x: auto; }}
            </style>
            </head>
            <body>
            <div class='container'>
                <h1>🛠️ Admin Debug Report</h1>
                {header_section}
                <div class='divider'></div>
                {stats_section}
                <div class='divider'></div>
                {links_section}
                <div class='divider'></div>
                {prompts_section}
                <div class='divider'></div>
                {data_section}
                <div class='footer small'>
                    Generated by RobinhoodService &middot; {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
                </div>
            </div>
            </body>
            </html>
            """

            return html_out

        except Exception as e:
            logger.error(f"Failed to generate debug report: {e}", exc_info=True)
            return self._generate_debug_fallback_report(str(e))

    def _generate_debug_header_section(self, dr: DebugReport, stats: Dict[str, Any], safe_escape) -> str:
        """Generate the debug report header section."""
        account_number = safe_escape(getattr(dr.portfolio_data.account_profile, 'account_number', 'N/A'))
        return f"""
            <div class='section'>
                <b>Generated:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
                <b>User:</b> {account_number}<br>
            </div>
        """

    def _generate_debug_stats_section(self, stats: Dict[str, Any], safe_escape) -> str:
        """Generate the debug report statistics section."""
        return f"""
            <div class='section'>
                <h2>Cache & Search Stats</h2>
                <ul>
                    <li><b>Cache Hits:</b> {safe_escape(stats.get('cache_hits', 0))}</li>
                    <li><b>Cache Misses/Fetches:</b> {safe_escape(stats.get('cache_misses', 0))}</li>
                    <li><b>Google Searches:</b> {safe_escape(stats.get('search_count', 0))}</li>
                    <li><b>GPT Token Usage:</b> {safe_escape(stats.get('gpt_tokens', 0))}</li>
                    <li><b>Total Execution Time:</b> {safe_escape(stats.get('total_execution_time_ms', 0))} ms</li>
                </ul>
            </div>
        """

    def _generate_debug_links_section(self, dr: DebugReport, safe_escape) -> str:
        """Generate the debug report links section."""
        links = []

        # Market conditions
        if dr.market_research.market_conditions:
            for article in dr.market_research.market_conditions:
                if getattr(article, 'link', None):
                    title = safe_escape(article.title)
                    link = safe_escape(article.link)
                    links.append(f"<li><a href='{link}' target='_blank'>{title}</a></li>")

        # Stock news
        if dr.market_research.stock_news:
            for sym, articles in dr.market_research.stock_news.items():
                for article in articles:
                    if getattr(article, 'link', None):
                        title = safe_escape(article.title)
                        link = safe_escape(article.link)
                        symbol = safe_escape(sym)
                        links.append(f"<li><a href='{link}' target='_blank'>{title} ({symbol})</a></li>")

        # Sector analysis
        if dr.market_research.sector_analysis:
            for article in dr.market_research.sector_analysis:
                if getattr(article, 'link', None):
                    title = safe_escape(article.title)
                    link = safe_escape(article.link)
                    links.append(f"<li><a href='{link}' target='_blank'>{title}</a></li>")

        links_html = "".join(links) if links else "<li>No article links found</li>"

        return f"""
            <div class='section'>
                <h2>All Article & Source Links</h2>
                <ul class='link-list'>
                    {links_html}
                </ul>
            </div>
        """

    def _generate_debug_prompts_section(self, dr: DebugReport, safe_escape) -> str:
        """Generate the debug report prompts section."""
        pulse_prompt = safe_escape(dr.prompts.get('pulse_prompt', 'No pulse prompt available'))
        gpt_analysis = safe_escape(dr.gpt_analysis)

        return f"""
            <div class='section'>
                <h2>Prompts & GPT Analysis</h2>
                <b>Pulse Prompt:</b>
                <pre>{pulse_prompt}</pre>
                <b>GPT Analysis:</b>
                <pre>{gpt_analysis}</pre>
            </div>
        """

    def _generate_debug_data_section(self, dr: DebugReport, safe_escape) -> str:
        """Generate the debug report raw data section."""
        try:
            portfolio_json = json.dumps(dr.portfolio_data.model_dump(), indent=2, ensure_ascii=False)
            market_json = json.dumps(dr.market_research.model_dump(), indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to serialize debug data: {e}")
            portfolio_json = f"Failed to serialize portfolio data: {e}"
            market_json = f"Failed to serialize market research data: {e}"

        return f"""
            <div class='section'>
                <h2>Raw Data Snapshots</h2>
                <b>Portfolio Data:</b>
                <pre>{safe_escape(portfolio_json)}</pre>
                <b>Market Research:</b>
                <pre>{safe_escape(market_json)}</pre>
            </div>
        """

    def _generate_debug_fallback_report(self, error_message: str) -> str:
        """Generate a fallback debug report when the main generation fails."""
        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #222;">
            <div style="max-width: 600px; margin: 30px auto; padding: 20px; background: #fff; border: 1px solid #ddd;">
                <h1 style="color: #c0392b;">🛠️ Debug Report Generation Error</h1>
                <p>Sorry, there was an error generating the debug report:</p>
                <p style="background: #f8f9fa; padding: 10px; border-radius: 4px; font-family: monospace;">
                    {html.escape(error_message)}
                </p>
                <p>Please check the logs for more details.</p>
                <p style="color: #888; font-size: 12px;">
                    Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
                </p>
            </div>
        </body>
        </html>
        """
