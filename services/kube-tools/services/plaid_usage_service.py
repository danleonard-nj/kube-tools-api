from typing import Any
from framework.logger import get_logger
from framework.configuration import Configuration
from httpx import AsyncClient
from openai import BaseModel
import pandas as pd
from pydantic import SecretStr
import os
import json
import datetime
import requests

import json
import base64
from datetime import datetime, timedelta, date
from io import BytesIO
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

from openai import OpenAI
from dotenv import load_dotenv

from clients.sib_client import SendInBlueClient
from models.bank_config import PlaidConfig
from models.openai_config import OpenAIConfig

PLAID_OAUTH_URL = "https://production.plaid.com/oauth/token"
PLAID_MCP_SSE = "https://api.dashboard.plaid.com/mcp/sse"


logger = get_logger(__name__)


# class PlaidUsageConfigModel(BaseModel):
#     client_id: str
#     secret: SecretStr
#     openai_api_key: SecretStr


class PlaidUsageService:
    def __init__(
        self,
        config: PlaidConfig,
        open_ai_config: OpenAIConfig,
        http_client: AsyncClient,
        openai_client: OpenAI,
        sib_client: SendInBlueClient
    ):
        self._config = config
        self._http_client = http_client
        self._openai_client = openai_client
        self._sib_client = sib_client

        self._client_id = config.client_id
        self._client_secret = config.client_secret

    # Simple CSS styles for diagnostic email
    EMAIL_STYLES = """
        body {
            font-family: Arial, sans-serif;
            line-height: 1.4;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }
        
        h1 {
            color: #333;
            border-bottom: 2px solid #ddd;
            padding-bottom: 10px;
        }
        
        h2 {
            color: #555;
            margin-top: 30px;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        
        th, td {
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }
        
        th {
            background-color: #f5f5f5;
            font-weight: bold;
        }
        
        .metric-section {
            margin: 30px 0;
            padding: 15px;
            border: 1px solid #ddd;
            background-color: #fafafa;
        }
        
        .raw-data {
            background-color: #f0f0f0;
            padding: 10px;
            margin: 10px 0;
            font-family: monospace;
            font-size: 12px;
            overflow-x: auto;
        }
    """

    def _get_prompt(
        self,
        from_date: str,
        to_date: str
    ):
        return f"""
        Call the Plaid MCP tool `plaid_get_usages` using this JSON as arguments:

        {{
        "team_id": "6086c47c1186c300100b83bf",
        "period_start": "{from_date}",
        "period_end": "{to_date}",
        "metric_types": [
            "auth-request",
            "balance-request",
            "transactions",
            "transactions-add",
            "transactions-remove",
            "transactions-active",
            "transactions-refresh",
            "identity-request"
        ]
        }}

        Return ONLY the JSON tool output, no prose.
        """

    async def _get_oauth_token(
        self
    ):
        """Create an OAuth access token for Plaid's Dashboard MCP server."""
        payload = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "client_credentials",
            "scope": "mcp:dashboard",
        }
        r = await self._http_client.post(PLAID_OAUTH_URL, json=payload, timeout=20)
        r.raise_for_status()
        return r.json()["access_token"]

    async def get_usage_data(
        self,
        days_back: int
    ):
        to_date = date.today()
        from_date = to_date - timedelta(days=days_back)

        dashboard_token = await self._get_oauth_token()
        logger.info(f"Obtained Plaid dashboard token: {dashboard_token}")

        # Ask the model to explicitly call the MCP tools we need and return JSON only.
        from_date = (date.today() - timedelta(days=days_back)).isoformat()
        to_date = date.today().isoformat()

        prompt = self._get_prompt(from_date, to_date)

        logger.info(f"Generated prompt for dates {from_date} to {to_date}: {prompt}")

        model = "gpt-4.1-mini"
        logger.info(f"Requesting Plaid MCP tool with prompt using model {model}.")

        resp = self._openai_client.responses.create(
            model=model,
            tools=[{
                "type": "mcp",
                "server_label": "plaid",
                "server_url": PLAID_MCP_SSE,
                "require_approval": "never",
                "headers": {"Authorization": "Bearer " + dashboard_token},
            }],
            input=prompt,
            temperature=0
        )

        logger.info(f"Received response from OpenAI: {resp.output}")

        raw_json = resp.model_dump(mode="json")
        with open("mcp_debug.json", "w", encoding="utf-8") as f:
            json.dump(raw_json, f, indent=2)

        usage_json = None
        for part in resp.output:
            # Grab tool output
            if part.type == "mcp_call" and part.name == "plaid_get_usages":
                try:
                    logger.info(f'Found MCP call "plaid_get_usages" with output: {part.output}')
                    usage_json = json.loads(part.output)
                    logger.info("Parsed JSON from tool output successfully.")
                    break
                except Exception as e:
                    logger.error(f"Error parsing tool output: {e}")

        if not usage_json:
            logger.error("No JSON parsed from response. Check MCP calls above and ensure your API key and Plaid team have access.")
            return {
                'html': '',
                'raw_usage': {},
                'error': 'No usage data available. Please check your API key and Plaid team access.'
            }

        html = self.generate_plaid_usage_email(usage_json, recipient_name='Dan')
        logger.info('Generated HTML email content for Plaid usage report.')

        await self._sib_client.send_email(
            recipient='dcl525@gmail.com',
            subject='Your Plaid Usage Report',
            html_body=html,
            from_name='KubeTools Plaid Usage Service',
            from_email='me@dan-leonard.com'
        )

        return {
            'html': html,
            'raw_usage': usage_json,
            'error': None

        }

    def generate_plaid_usage_email(self, plaid_data, recipient_name="User"):
        """
        Generate a nice HTML email with Plaid usage statistics and graphs.

        Args:
            plaid_data (dict): The Plaid usage data in JSON format
            recipient_name (str): Name of the email recipient

        Returns:
            str: HTML email content
        """

        # Pricing per request in USD
        pricing = {
            "auth-request": 0.30,
            "balance-request": 0.05,
            "transactions": 0.05,
            "transactions-add": 0.05,
            "transactions-remove": 0.05,
            "transactions-active": 0.05,
            "transactions-refresh": 0.05,
            "identity-request": 1.00
        }

        def calculate_summary_stats(series_data, metric_name, pricing):
            """Calculate summary statistics for a data series"""
            data = series_data.get('series', [])
            # If the metric is a monthly cumulative counter (Plaid returns
            # cumulative counts that reset at the beginning of each month for
            # some metrics like `balance-request`), convert to per-day
            # increments before computing totals.

            def _cumulative_to_increments(arr):
                if not arr:
                    return []
                increments = []
                prev = None
                for v in arr:
                    try:
                        v_num = int(v)
                    except Exception:
                        # non-numeric values -> treat as zero
                        v_num = 0
                    if prev is None:
                        increments.append(v_num)
                    else:
                        if v_num >= prev:
                            increments.append(v_num - prev)
                        else:
                            # reset detected (likely new month) -> treat
                            # current value as the day's count
                            increments.append(v_num)
                    prev = v_num
                return increments

            # Use incremental values for balance-request which Plaid reports
            # as cumulative-per-month (resets to a small number on month start).
            if metric_name == 'balance-request':
                computed_series = _cumulative_to_increments(data)
            else:
                # try to coerce to ints for other metrics as well
                computed_series = []
                for v in data:
                    try:
                        computed_series.append(int(v))
                    except Exception:
                        computed_series.append(0)
            total_requests = sum(computed_series)
            cost_per_request = pricing.get(metric_name, 0.0)
            total_cost = total_requests * cost_per_request

            avg = round((sum(computed_series) / len(computed_series)), 2) if computed_series else 0
            mx = max(computed_series) if computed_series else 0
            mn = min(computed_series) if computed_series else 0

            return {
                'total': total_requests,
                'average': avg,
                'max': mx,
                'min': mn,
                'observations': len(computed_series),
                'cost_per_request': cost_per_request,
                'total_cost': total_cost,
                'computed_series': computed_series,
            }

        # Parse data and calculate statistics
        series = plaid_data['series']
        summary_data = []

        for metric in series:
            metric_name = metric['metricName']

            # Calculate stats
            stats = calculate_summary_stats(metric, metric_name, pricing)
            stats['name'] = metric_name.replace('-', ' ').title()
            stats['period'] = f"{metric['start'][:10]} to {metric['end'][:10]}" if 'end' in metric else f"From {metric['start'][:10]}"
            summary_data.append(stats)

        # Generate simple diagnostic HTML email
        current_date = datetime.now().strftime('%B %d, %Y')

        def _create_chart_base64(series_values, start_date_str=None, title=None):
            """Render a simple line chart and return a base64 PNG data URI string.

            series_values: list[int]
            start_date_str: ISO date (YYYY-MM-DD) for first point, optional
            title: chart title
            Returns: str or None
            """
            if not series_values:
                return None

            # Try to build x axis dates from start_date_str
            x_vals = None
            if start_date_str:
                try:
                    start_dt = datetime.fromisoformat(start_date_str[:10])
                    x_vals = [start_dt + timedelta(days=i) for i in range(len(series_values))]
                except Exception:
                    x_vals = list(range(len(series_values)))
            else:
                x_vals = list(range(len(series_values)))

            plt.switch_backend('Agg')
            fig, ax = plt.subplots(figsize=(6, 2.5))
            try:
                ax.plot(x_vals, series_values, marker='o', linewidth=1)
                if isinstance(x_vals[0], datetime):
                    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
                    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
                    fig.autofmt_xdate(rotation=45)
                ax.set_ylabel('Requests')
                if title:
                    ax.set_title(title, fontsize=10)
                ax.grid(alpha=0.25)

                buf = BytesIO()
                fig.tight_layout()
                fig.savefig(buf, format='png', dpi=100)
                buf.seek(0)
                img_b64 = base64.b64encode(buf.read()).decode('ascii')
                return f"data:image/png;base64,{img_b64}"
            finally:
                plt.close(fig)

        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Plaid Usage Diagnostic Report</title>
    <style>
{self.EMAIL_STYLES}
    </style>
</head>
<body>
    <h1>Plaid Usage Diagnostic Report</h1>
    <p><strong>Generated:</strong> {current_date}</p>
    <p><strong>Recipient:</strong> {recipient_name}</p>

    <h2>Summary Table</h2>
    <table>
        <tr>
            <th>Metric</th>
            <th>Total Requests</th>
            <th>Daily Average</th>
            <th>Peak Day</th>
            <th>Min Day</th>
            <th>Period (Days)</th>
            <th>Cost per Request</th>
            <th>Total Cost</th>
        </tr>"""

        # Add table rows for each metric
        total_requests = 0
        total_cost = 0

        for stat in summary_data:
            total_requests += stat['total']
            total_cost += stat['total_cost']
            html_content += f"""
        <tr>
            <td>{stat['name']}</td>
            <td>{stat['total']:,}</td>
            <td>{stat['average']}</td>
            <td>{stat['max']}</td>
            <td>{stat['min']}</td>
            <td>{stat['observations']}</td>
            <td>${stat['cost_per_request']:.2f}</td>
            <td>${stat['total_cost']:.2f}</td>
        </tr>"""

        html_content += f"""
    </table>

    <h2>Totals</h2>
    <table>
        <tr><td><strong>Total API Requests</strong></td><td>{total_requests:,}</td></tr>
        <tr><td><strong>Total Estimated Cost</strong></td><td>${total_cost:.2f}</td></tr>
        <tr><td><strong>Average Daily Cost</strong></td><td>${(total_cost / max(1, summary_data[0]['observations']) if summary_data else 0):.2f}</td></tr>
    </table>
"""
        with open(f"plaid_usage_report_{current_date}.html", "w", encoding="utf-8") as file:
            file.write(html_content)

        return html_content
