from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import html
from typing import Any

from framework.logger import get_logger

logger = get_logger(__name__)


def get_styles() -> str:
    return """
<style>
    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }

    body {
        font-family: Arial, sans-serif;
        line-height: 1.6;
        color: #333;
        background-color: #f8fafc;
    }

    .container {
        max-width: 600px;
        margin: 0 auto;
        background-color: #ffffff;
    }

    .header {
        background: #1e40af;
        color: white;
        padding: 30px 20px;
        text-align: center;
    }

    .header h1 {
        font-size: 28px;
        font-weight: 700;
        margin-bottom: 8px;
    }

    .header p {
        font-size: 16px;
        opacity: 0.9;
    }

    .content {
        padding: 0;
    }

    .post-card {
        border-bottom: 1px solid #e5e7eb;
        padding: 24px;
    }

    .post-card:last-child {
        border-bottom: none;
    }

    /* Email-friendly badge styles */
    .post-badge {
        background-color: #dbeafe;
        color: #1e40af;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        line-height: 1.2;
        display: inline-block;
    }

    /* Email-friendly date styles */
    .post-date {
        color: #6b7280;
        font-size: 14px;
        line-height: 1.2;
        font-weight: normal;
    }

    .post-content {
        background-color: #f8fafc;
        border-left: 4px solid #3b82f6;
        padding: 16px;
        border-radius: 0 8px 8px 0;
        margin-bottom: 20px;
    }

    .post-text {
        font-size: 16px;
        line-height: 1.7;
        color: #374151;
    }

    .ai-summary-section {
        background-color: #f0f9ff;
        border: 1px solid #bae6fd;
        border-radius: 8px;
        padding: 16px;
    }

    .ai-icon {
        width: 20px;
        height: 20px;
        background-color: #0ea5e9;
        border-radius: 50%;
        display: inline-block;
        text-align: center;
        color: white;
        font-size: 12px;
        font-weight: bold;
        line-height: 20px;
        vertical-align: middle;
    }

    .ai-summary-title {
        font-size: 14px;
        font-weight: 600;
        color: #0c4a6e;
        line-height: 20px;
        vertical-align: middle;
        margin: 0;
        padding: 0;
    }

    .ai-summary-text {
        font-size: 14px;
        color: #0c4a6e;
        line-height: 1.6;
    }

    .post-link {
        margin-top: 16px;
    }

    .post-link a {
        color: #3b82f6;
        text-decoration: none;
        font-size: 14px;
        font-weight: 500;
    }

    .footer {
        background-color: #f8fafc;
        padding: 24px;
        text-align: center;
        border-top: 1px solid #e5e7eb;
    }

    .footer p {
        color: #6b7280;
        font-size: 14px;
        margin-bottom: 8px;
    }

    .footer a {
        color: #3b82f6;
        text-decoration: none;
    }

    /* Mobile styles */
    @media only screen and (max-width: 600px) {
        .container {
            margin: 0;
        }

        .header {
            padding: 20px 16px;
        }

        .header h1 {
            font-size: 24px;
        }

        .post-card {
            padding: 20px 16px;
        }

        .post-content {
            padding: 12px;
        }

        .post-text {
            font-size: 15px;
        }
    }

    /* Table reset for email clients */
    table {
        border-collapse: collapse;
        mso-table-lspace: 0pt;
        mso-table-rspace: 0pt;
    }

    td {
        border-collapse: collapse;
        vertical-align: middle;
    }
</style>
"""


def generate_truth_social_email(posts_data: list[dict[str, Any]], max_posts: int = 10) -> str:
    """Generate HTML email from Truth Social posts with AI summaries."""
    logger.info(f"Generating email for {len(posts_data)} posts (max: {max_posts})")

    def format_timestamp_to_eastern(timestamp: int) -> str:
        """Convert Unix timestamp to Eastern Time format."""
        try:
            dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            dt_et = dt_utc.astimezone(ZoneInfo("America/New_York"))
            now_et = datetime.now(ZoneInfo("America/New_York"))

            day_str = "Today" if dt_et.date() == now_et.date() else dt_et.strftime("%A")
            return f"{day_str}, {dt_et.strftime('%B %d, %Y • %I:%M %p ET')}"
        except Exception as e:
            logger.error(f"Failed to format timestamp {timestamp}: {e}")
            return f"Invalid timestamp: {timestamp}"

    def format_date_fallback(date_string: str) -> str:
        """Fallback for legacy date string format."""
        try:
            dt = datetime.strptime(date_string, "%a, %d %b %Y %H:%M:%S %z")
            dt_et = dt.astimezone(ZoneInfo("America/New_York"))
            now_et = datetime.now(ZoneInfo("America/New_York"))

            day_str = "Today" if dt_et.date() == now_et.date() else dt_et.strftime("%A")
            return f"{day_str}, {dt_et.strftime('%B %d, %Y • %I:%M %p ET')}"
        except Exception as e:
            logger.warning(f"Failed to parse date string '{date_string}': {e}")
            return date_string

    def get_ai_summary_section(formatted_ai_summary: str) -> str:
        """Generate AI summary section if summary is available."""
        if 'No summary available' in formatted_ai_summary or 'No AI analysis available' in formatted_ai_summary:
            return ''
        return f"""
            <div class="ai-summary-section">
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 12px;">
                    <tr>
                        <td style="vertical-align: middle; width: 28px;">
                            <div class="ai-icon">AI</div>
                        </td>
                        <td style="vertical-align: middle; padding-left: 8px;">
                            <div class="ai-summary-title">AI Analysis</div>
                        </td>
                    </tr>
                </table>
                <div class="ai-summary-text">
                    {formatted_ai_summary}
                </div>
            </div>
            """

    posts_to_include = posts_data[:max_posts]
    logger.info(f"Generating HTML for {len(posts_to_include)} posts")
    post_cards_html = ""

    for idx, post in enumerate(posts_to_include, 1):
        # Use new timestamp format, fallback to legacy format
        if 'published_timestamp' in post:
            formatted_date = format_timestamp_to_eastern(post['published_timestamp'])
        else:
            published = post.get('published', '')
            formatted_date = format_date_fallback(published)
            logger.debug(f"Post {idx}: Using legacy date format")

        link = post.get('original_link', post.get('link', '#'))
        ai_summary = post.get('ai_summary', 'No AI analysis available')
        content = post.get('summary', 'No content available')

        # Escape and format AI summary
        escaped_ai_summary = html.escape(ai_summary)
        formatted_ai_summary = escaped_ai_summary.replace('\n', '<br>')

        post_card_html = f"""
            <div class="post-card">
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom: 16px;">
                    <tr>
                        <td style="vertical-align: middle;">
                            <div class="post-badge">Truth Post</div>
                        </td>
                        <td style="vertical-align: middle; text-align: right;">
                            <div class="post-date">{formatted_date}</div>
                        </td>
                    </tr>
                </table>
                <div class="post-content">
                    <div class="post-text">
                        {content}
                    </div>
                </div>
                {get_ai_summary_section(formatted_ai_summary)}
                <div class="post-link">
                    <a href="{link}" target="_blank">
                        View Original Post →
                    </a>
                </div>
            </div>"""

        post_cards_html += post_card_html

    post_plural = "posts" if len(posts_to_include) > 1 else "post"
    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Truth Social Updates</title>
    {get_styles()}
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Truth Social Updates</h1>
            <p>Latest posts and AI analysis • {len(posts_to_include)} {post_plural}</p>
        </div>
        <div class="content">
            {post_cards_html}
        </div>
        <div class="footer">
            <p style="font-size: 12px; color: #9ca3af;">
                AI Summaries powered by GPT-4O Mini<br>
            </p>
            <p style="font-size: 12px; color: #9ca3af;">
                This email was sent by Truth Social Updates<br>
                © 2025 Truth Social. All rights reserved.
            </p>
        </div>
    </div>
</body>
</html>"""

    logger.info("Email HTML generated successfully")
    return html_template
