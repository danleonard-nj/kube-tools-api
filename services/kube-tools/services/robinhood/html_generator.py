

from typing import Any, List, Optional
from framework.logger import get_logger

from models.robinhood_models import SectionTitle, SummarySection, TruthSocialInsights, TruthSocialPost

logger = get_logger(__name__)


def generate_simplified_trading_implications_html(impact_score: float, sentiment_analysis: dict) -> str:
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


def analyze_market_and_policy_combined_html(market_posts: list[TruthSocialPost], policy_posts: list[TruthSocialPost], sentiment_analysis: dict) -> str:
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

    # Get top 3 most impactful posts - FIX: Add proper sorting logic
    all_posts_with_scores = []

    # TODO: Define a function to generate impact scores for posts (GPT 3.5 call?)
    def generate_impact_score(post: TruthSocialPost) -> int:
        return 8 if post.market_impact else 0

    # Process market-relevant posts
    for post in market_posts:
        all_posts_with_scores.append({
            'post': post.original_post,
            'impact_score': generate_impact_score(post),
            'analysis': post.market_analysis or '',
            'type': 'Market'
        })

    # Process trend-significant posts
    for post in policy_posts:
        original_post = post.original_post
        impact_score = 6 if post.trend_significance else 0
        analysis = post.trend_analysis or ''
        post_id = original_post.post_id

        # Check for duplicates - FIX: Handle both dict and object cases in existing posts
        is_duplicate = False
        for existing_post_data in all_posts_with_scores:
            existing_post = existing_post_data['post']
            existing_post_id = existing_post.post_id

            if post_id and post_id == existing_post_id:
                is_duplicate = True
                break

        if not is_duplicate:
            all_posts_with_scores.append({
                'post': original_post,
                'impact_score': impact_score,
                'analysis': analysis,
                'type': 'Policy'
            })

    # Sort by impact score and take top 3
    all_posts_with_scores.sort(key=lambda x: x['impact_score'], reverse=True)
    top_3_posts = all_posts_with_scores[:3]

    top_posts_html = ""
    for i, post_data in enumerate(top_3_posts):
        post = post_data['post']
        content = post.content or post.title
        timestamp = post.published_date or 'Recent'
        formatted_time = timestamp.strftime('%m/%d %H:%M')
        impact_score = post_data['impact_score']
        analysis = post_data['analysis']
        impact_class = 'positive' if impact_score >= 7 else ''

        top_posts_html += f"""
        <div style="border-left: 4px solid #2a5298; padding: 16px; margin-bottom: 12px; border-radius: 4px;">
            <div style="font-weight: 600; color: #2a5298; margin-bottom: 8px;">
                {formatted_time} • <span class="{impact_class}">Impact: {impact_score}/10</span> • {post_data['type']}
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
    <div class="section pipeline-section">
        <h4 style="color: #2a5298; margin-top: 0;">Market-Moving Communications</h4>
        
        {sentiment_html}
        
        <h4 style="color: #2a5298; margin-top: 24px; margin-bottom: 16px;">Top Impact Posts</h4>
        {top_posts_html if top_posts_html else '<p style="color: #5f6368; font-style: italic;">No significant posts found.</p>'}
        
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


def create_top_impact_posts_html_table(market_posts: List[Any], trend_posts: List[Any]) -> Optional[str]:
    """Create HTML table for top impact Truth Social posts."""
    try:
        # Combine and sort posts by impact score
        all_posts = []

        # Process market-relevant posts
        for post in market_posts:
            # if isinstance(post, dict):
            #     original_post = post.get('original_post', {})
            #     market_impact_score = 8 if post.get('market_impact', False) else 0
            #     analysis = post.get('market_analysis', '')
            # else:
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
            # if isinstance(post, dict):
            #     original_post = post.get('original_post', {})
            #     trend_impact_score = 6 if post.get('trend_significance', False) else 0
            #     analysis = post.get('trend_analysis', '')
            # else:
            original_post = post.original_post
            trend_impact_score = 6 if post.trend_significance else 0
            analysis = post.trend_analysis or ''

            # Only add if not already added as market post
            post_id = original_post.post_id
            if not any(p['post'].post_id == post_id for p in all_posts):
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
            # if isinstance(post, dict):
            #     date = post.get('published_date', 'Unknown')
            #     content = post.get('content', post.get('title', ''))
            #     link = post.get('link', '')
            # else:
            date = post.published_date or 'Unknown'
            content = post.content or post.title
            link = getattr(post, 'link', '')

            # Format date
            # if hasattr(date, 'strftime'):
            formatted_date = date.strftime('%m/%d %H:%M')
            # elif isinstance(date, str) and date != 'Unknown':
            #     try:
            #         from datetime import datetime
            #         parsed_date = datetime.fromisoformat(date.replace('Z', '+00:00'))
            #         formatted_date = parsed_date.strftime('%m/%d %H:%M')
            #     except:
            #         formatted_date = date
            # else:
            #     formatted_date = str(date)

            analysis_text = post_data['analysis']

            # Impact score styling
            impact_score = post_data['impact_score']
            impact_class = 'positive' if impact_score >= 7 else 'negative' if impact_score <= 3 else ''

            # Type badge styling
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


def create_truth_social_summary_sections(insights: Optional[TruthSocialInsights]) -> List[SummarySection]:
    """Create streamlined summary sections for Truth Social insights with HTML formatting."""
    if not insights:
        return []

    market_relevant_posts = insights.market_relevant_posts
    trend_significant_posts = insights.trend_significant_posts
    total_analyzed = insights.total_posts_analyzed
    date_range = insights.date_range
    sentiment_analysis = insights.sentiment_analysis
    market_impact_score = insights.market_impact_score

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
        <div class="section pipeline-section">
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

        sections.append(SummarySection(title=SectionTitle.PRESIDENTIAL_INTELLIGENCE_BRIEF, data=executive_summary, type='html'))

    # 2. TOP IMPACT POSTS TABLE
    if market_relevant_posts or trend_significant_posts:
        top_posts_table = create_top_impact_posts_html_table(market_relevant_posts, trend_significant_posts)
        if top_posts_table:
            sections.append(SummarySection(title=SectionTitle.TOP_IMPACT_POSTS, data=top_posts_table, type='html'))

    # 3. Market Impact & Policy Analysis (Combined)
    if market_relevant_posts:
        combined_analysis = analyze_market_and_policy_combined_html(market_relevant_posts, trend_significant_posts, sentiment_analysis)
        sections.append(SummarySection(title=SectionTitle.MARKET_IMPACT_POLICY_ANALYSIS, data=combined_analysis, type='html'))

    # 4. Trading Strategy Implications
    if market_relevant_posts or trend_significant_posts:
        strategy_implications = generate_simplified_trading_implications_html(market_impact_score, sentiment_analysis)
        sections.append(SummarySection(title=SectionTitle.TRADING_STRATEGY_IMPLICATIONS, data=strategy_implications, type='html'))

    return sections
