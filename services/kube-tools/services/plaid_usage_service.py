from typing import Any, List, Dict, Optional, Tuple
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

from openai import AsyncOpenAI
from dotenv import load_dotenv

from clients.sib_client import SendInBlueClient
from domain.gpt import GPTModel
from models.bank_config import PlaidConfig
from models.openai_config import OpenAIConfig

PLAID_OAUTH_URL = "https://production.plaid.com/oauth/token"
PLAID_MCP_SSE = "https://api.dashboard.plaid.com/mcp/sse"


PRICING = {
    "auth-request": 0.30,
    "balance-request": 0.05,
    "transactions": 0.05,
    "transactions-add": 0.05,
    "transactions-remove": 0.05,
    "transactions-active": 0.05,
    "transactions-refresh": 0.05,
    "identity-request": 1.00
}

EMAIL_STYLES = """
PRICING = {
    "auth-request": 0.30,
    "balance-request": 0.05,
    "transactions": 0.05,
    "transactions-add": 0.05,
    "transactions-remove": 0.05,
    "transactions-active": 0.05,
    "transactions-refresh": 0.05,
    "identity-request": 1.00
}

EMAIL_STYLES = """
        body {
            font-family: Arial, sans-serif;
            line-height: 1.4;
            color:  # 333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }

        h1 {
            color:  # 333;
            border-bottom: 2px solid  # ddd;
            padding-bottom: 10px;
        }

        h2 {
            color:  # 555;
            margin-top: 30px;
        }

        table {
            width: 100 %;
            border-collapse: collapse;
            margin: 20px 0;
        }

        th, td {
            border: 1px solid  # ddd;
            padding: 8px;
            text-align: left;
        }

        th {
            background-color:  # f5f5f5;
            font-weight: bold;
        }

        .metric-section {
            margin: 30px 0;
            padding: 15px;
            border: 1px solid  # ddd;
            background-color:  # fafafa;
        }

        .raw-data {
            background-color:  # f0f0f0;
            padding: 10px;
            margin: 10px 0;
            font-family: monospace;
            font-size: 12px;
            overflow-x: auto;
        }

        .warning {
            background-color:  # fff3cd;
            border: 1px solid  # ffc107;
            color:  # 856404;
            padding: 10px;
            margin: 10px 0;
            border-radius: 4px;
        }
    """

logger = get_logger(__name__)


class PlaidUsageService:
    def __init__(
        self,
        config: PlaidConfig,
        open_ai_config: OpenAIConfig,
        http_client: AsyncClient,
        openai_client: AsyncOpenAI,
        sib_client: SendInBlueClient
    ):
        self._config = config
        self._http_client = http_client
        self._openai_client = openai_client
        self._sib_client = sib_client

        self._client_id = config.client_id
        self._client_secret = config.client_secret

    # Simple CSS styles for diagnostic email

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
        to_date_dt = date.today()
        from_date_dt = to_date_dt - timedelta(days=days_back)
        to_date_dt = date.today()
        from_date_dt = to_date_dt - timedelta(days=days_back)

        dashboard_token = await self._get_oauth_token()
        logger.info(f"Obtained Plaid dashboard token: {dashboard_token}")

        # Ask the model to explicitly call the MCP tools we need and return JSON only.
        from_date = from_date_dt.isoformat()
        to_date = to_date_dt.isoformat()
        from_date = from_date_dt.isoformat()
        to_date = to_date_dt.isoformat()

        prompt = self._get_prompt(from_date, to_date)

        logger.info(f"Generated prompt for dates {from_date} to {to_date}")
        logger.info(f"Generated prompt for dates {from_date} to {to_date}")

        logger.info(f"Requesting Plaid MCP tool with prompt using model {GPTModel.GPT_4_1}.")

        resp = await self._openai_client.responses.create(
            model=GPTModel.GPT_4_1,
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

        html = self.generate_plaid_usage_email(
            usage_json,
            start_date=from_date_dt,
            end_date=to_date_dt
        )
        html = self.generate_plaid_usage_email(
            usage_json,
            start_date=from_date_dt,
            end_date=to_date_dt
        )
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

    def _parse_date_safely(self, date_str: str) -> Optional[datetime]:
        """Safely parse a date string to datetime object."""
        if not date_str:
            return None
        try:
            # Handle ISO format with or without time component
            if 'T' in date_str:
                return datetime.fromisoformat(date_str.split('T')[0])
            return datetime.strptime(date_str[:10], '%Y-%m-%d')
        except Exception as e:
            logger.warning(f"Failed to parse date '{date_str}': {e}")
            return None

    def _generate_date_series(self, start_date: datetime, num_points: int) -> List[datetime]:
        """Generate a series of dates starting from start_date."""
        return [start_date + timedelta(days=i) for i in range(num_points)]

    def _is_cumulative_metric(self, metric_name: str) -> bool:
        """Determine if a metric is cumulative (resets monthly)."""
        # Add metric names that are known to be cumulative
        cumulative_metrics = {
            'balance-request'
        }
        return metric_name in cumulative_metrics

    def _convert_cumulative_to_daily(
        self,
        values: List[Any],
        dates: List[datetime],
        metric_name: str
    ) -> Tuple[List[int], List[str]]:
        """
        Convert cumulative monthly values to daily increments.
    def _parse_date_safely(self, date_str: str) -> Optional[datetime]:
        """Safely parse a date string to datetime object."""
        if not date_str:
            return None
        try:
            # Handle ISO format with or without time component
            if 'T' in date_str:
                return datetime.fromisoformat(date_str.split('T')[0])
            return datetime.strptime(date_str[:10], '%Y-%m-%d')
        except Exception as e:
            logger.warning(f"Failed to parse date '{date_str}': {e}")
            return None

    def _generate_date_series(self, start_date: datetime, num_points: int) -> List[datetime]:
        """Generate a series of dates starting from start_date."""
        return [start_date + timedelta(days=i) for i in range(num_points)]

    def _is_cumulative_metric(self, metric_name: str) -> bool:
        """Determine if a metric is cumulative (resets monthly)."""
        # Add metric names that are known to be cumulative
        cumulative_metrics = {
            'balance-request'
        }
        return metric_name in cumulative_metrics

    def _convert_cumulative_to_daily(
        self,
        values: List[Any],
        dates: List[datetime],
        metric_name: str
    ) -> Tuple[List[int], List[str]]:
        """
        Convert cumulative monthly values to daily increments.

        Args:
            values: List of values (cumulative or daily)
            dates: List of corresponding dates
            metric_name: Name of the metric
            values: List of values (cumulative or daily)
            dates: List of corresponding dates
            metric_name: Name of the metric

        Returns:
            Tuple of (daily_values, warnings)
        """
        if not values or not dates:
            return [], []

        if len(values) != len(dates):
            logger.warning(f"Values and dates length mismatch: {len(values)} vs {len(dates)}")
            # Truncate to shorter length
            min_len = min(len(values), len(dates))
            values = values[:min_len]
            dates = dates[:min_len]

        daily_values = []
        warnings = []
        prev_value = None
        prev_date = None
        current_month_start_value = None

        for i, (val, dt) in enumerate(zip(values, dates)):
            # Convert value to integer
            try:
                current_value = int(val) if val is not None else 0
            except (ValueError, TypeError):
                current_value = 0
                warnings.append(f"Non-numeric value at index {i}: {val}")

            if prev_date is None:
                # First data point
                daily_values.append(current_value)
                current_month_start_value = 0  # Assume month starts at 0
            else:
                # Check if we've crossed a month boundary
                month_changed = (dt.year != prev_date.year or dt.month != prev_date.month)

                if month_changed:
                    # New month - value should be the daily count for this day
                    daily_values.append(current_value)
                    current_month_start_value = 0
                    logger.debug(f"Month boundary detected between {prev_date.date()} and {dt.date()}")
                else:
                    # Same month - calculate increment
                    if current_value >= prev_value:
                        # Normal case: cumulative increased
                        increment = current_value - prev_value
                        daily_values.append(increment)
            Tuple of (daily_values, warnings)
        """
        if not values or not dates:
            return [], []

        if len(values) != len(dates):
            logger.warning(f"Values and dates length mismatch: {len(values)} vs {len(dates)}")
            # Truncate to shorter length
            min_len = min(len(values), len(dates))
            values = values[:min_len]
            dates = dates[:min_len]

        daily_values = []
        warnings = []
        prev_value = None
        prev_date = None
        current_month_start_value = None

        for i, (val, dt) in enumerate(zip(values, dates)):
            # Convert value to integer
            try:
                current_value = int(val) if val is not None else 0
            except (ValueError, TypeError):
                current_value = 0
                warnings.append(f"Non-numeric value at index {i}: {val}")

            if prev_date is None:
                # First data point
                daily_values.append(current_value)
                current_month_start_value = 0  # Assume month starts at 0
            else:
                # Check if we've crossed a month boundary
                month_changed = (dt.year != prev_date.year or dt.month != prev_date.month)

                if month_changed:
                    # New month - value should be the daily count for this day
                    daily_values.append(current_value)
                    current_month_start_value = 0
                    logger.debug(f"Month boundary detected between {prev_date.date()} and {dt.date()}")
                else:
                    # Same month - calculate increment
                    if current_value >= prev_value:
                        # Normal case: cumulative increased
                        increment = current_value - prev_value
                        daily_values.append(increment)
                    else:
                        # Unexpected: value decreased within same month
                        # This might indicate missing data or an error
                        warnings.append(
                            f"Unexpected decrease within month at {dt.date()}: "
                            f"{prev_value} -> {current_value}"
                        )
                        # Use the current value as-is (might be a correction)
                        daily_values.append(max(0, current_value))

            prev_value = current_value
            prev_date = dt

        return daily_values, warnings

    def calculate_summary_stats(self, series_data: Dict, metric_name: str, pricing: Dict) -> Dict:
        """
        Calculate summary statistics for a data series with proper date handling.

        Args:
            series_data: Dictionary containing series data from Plaid
            metric_name: Name of the metric
            pricing: Dictionary of pricing per request type

        Returns:
            Dictionary of calculated statistics
        """
        data = series_data.get('series', [])
        start_date_str = series_data.get('start', '')
        # end_date_str = series_data.get('end', '')

        # Parse start date
        start_date = self._parse_date_safely(start_date_str)
        if not start_date:
            logger.warning(f"Could not parse start date for {metric_name}: {start_date_str}")
            # Fallback to simple conversion without date awareness
            computed_series = [int(v) if v else 0 for v in data]
            warnings = ["Date parsing failed; treating as daily values"]
        else:
            # Generate date series
            dates = self._generate_date_series(start_date, len(data))

            # Check if this metric is cumulative
            if self._is_cumulative_metric(metric_name):
                computed_series, warnings = self._convert_cumulative_to_daily(
                    data, dates, metric_name
                )
                logger.info(f"Converted cumulative data for {metric_name}: "
                            f"{len(data)} cumulative -> {len(computed_series)} daily values")
            else:
                # Non-cumulative metric - just convert to integers
                # Non-cumulative metric - just convert to integers
                computed_series = []
                warnings = []
                for i, v in enumerate(data):
                warnings = []
                for i, v in enumerate(data):
                    try:
                        computed_series.append(int(v) if v is not None else 0)
                    except (ValueError, TypeError):
                        computed_series.append(int(v) if v is not None else 0)
                    except (ValueError, TypeError):
                        computed_series.append(0)
                        warnings.append(f"Non-numeric value at index {i}: {v}")

        # Calculate statistics
        total_requests = sum(computed_series)
        cost_per_request = pricing.get(metric_name, 0.0)
        total_cost = total_requests * cost_per_request
                        warnings.append(f"Non-numeric value at index {i}: {v}")

        # Calculate statistics
        total_requests = sum(computed_series)
        cost_per_request = pricing.get(metric_name, 0.0)
        total_cost = total_requests * cost_per_request

        if computed_series:
            avg = round(sum(computed_series) / len(computed_series), 2)
            mx = max(computed_series)
            mn = min(computed_series)
        else:
            avg = mx = mn = 0
        if computed_series:
            avg = round(sum(computed_series) / len(computed_series), 2)
            mx = max(computed_series)
            mn = min(computed_series)
        else:
            avg = mx = mn = 0

        return {
            'total': total_requests,
            'average': avg,
            'max': mx,
            'min': mn,
            'observations': len(computed_series),
            'cost_per_request': cost_per_request,
            'total_cost': total_cost,
            'computed_series': computed_series,
            'start_date': start_date,
            'warnings': warnings
        }

    def generate_plaid_usage_email(
        self,
        plaid_data: Dict,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> str:
        """
        Generate a nice HTML email with Plaid usage statistics and graphs.

        Args:
            plaid_data: The Plaid usage data in JSON format
            recipient_name: Name of the email recipient

        Returns:
            HTML email content
        """
        # Pricing per request in USD
        return {
            'total': total_requests,
            'average': avg,
            'max': mx,
            'min': mn,
            'observations': len(computed_series),
            'cost_per_request': cost_per_request,
            'total_cost': total_cost,
            'computed_series': computed_series,
            'start_date': start_date,
            'warnings': warnings
        }

    def generate_plaid_usage_email(
        self,
        plaid_data: Dict,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> str:
        """
        Generate a nice HTML email with Plaid usage statistics and graphs.

        Args:
            plaid_data: The Plaid usage data in JSON format
            recipient_name: Name of the email recipient

        Returns:
            HTML email content
        """
        # Pricing per request in USD

        # Parse data and calculate statistics
        series = plaid_data.get('series', [])
        series = plaid_data.get('series', [])
        summary_data = []
        all_warnings = []
        all_warnings = []

        for metric in series:
            metric_name = metric.get('metricName', 'unknown')
            metric_name = metric.get('metricName', 'unknown')

            # Calculate stats with improved logic
            stats = self.calculate_summary_stats(metric, metric_name, PRICING)
            # Calculate stats with improved logic
            stats = self.calculate_summary_stats(metric, metric_name, PRICING)
            stats['name'] = metric_name.replace('-', ' ').title()
            stats['metric_name'] = metric_name

            # Format period
            start_str = metric.get('start', '')[:10] if 'start' in metric else 'Unknown'
            end_str = metric.get('end', '')[:10] if 'end' in metric else 'Unknown'
            stats['period'] = f"{start_str} to {end_str}"

            stats['metric_name'] = metric_name

            # Format period
            start_str = metric.get('start', '')[:10] if 'start' in metric else 'Unknown'
            end_str = metric.get('end', '')[:10] if 'end' in metric else 'Unknown'
            stats['period'] = f"{start_str} to {end_str}"

            summary_data.append(stats)

            # Collect warnings
            if stats.get('warnings'):
                all_warnings.extend([f"{metric_name}: {w}" for w in stats['warnings']])

            # Collect warnings
            if stats.get('warnings'):
                all_warnings.extend([f"{metric_name}: {w}" for w in stats['warnings']])

        # Generate simple diagnostic HTML email
        current_date = datetime.now().strftime('%B %d, %Y')

        start_date_str = start_date.strftime('%B %d, %Y') if start_date else 'Unknown'
        end_date_str = end_date.strftime('%B %d, %Y') if end_date else 'Unknown'
        start_date_str = start_date.strftime('%B %d, %Y') if start_date else 'Unknown'
        end_date_str = end_date.strftime('%B %d, %Y') if end_date else 'Unknown'

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Plaid Usage Report</title>
            <style>
        {EMAIL_STYLES}
            </style>
        </head>
        <body>
            <h1>Plaid Usage Report</h1>
            <p><strong>Generated:</strong> {current_date}</p>
            <p><strong>Start Date:</strong> {start_date_str}</p>
            <p><strong>End Date:</strong> {end_date_str}</p>
        """

        # Add warnings section if there are any
        if all_warnings:
            html_content += """
        <div class="warning">
        <strong>Data Processing Warnings:</strong>
        <ul>"""
            for warning in all_warnings:
                html_content += f"<li>{warning}</li>"
                html_content += """
            </ul>
        </div>"""

        html_content += """
        <h2>Summary Table</h2>
        <table>
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Plaid Usage Report</title>
            <style>
        {EMAIL_STYLES}
            </style>
        </head>
        <body>
            <h1>Plaid Usage Report</h1>
            <p><strong>Generated:</strong> {current_date}</p>
            <p><strong>Start Date:</strong> {start_date_str}</p>
            <p><strong>End Date:</strong> {end_date_str}</p>
        """

        # Add warnings section if there are any
        if all_warnings:
            html_content += """
        <div class="warning">
        <strong>Data Processing Warnings:</strong>
        <ul>"""
            for warning in all_warnings:
                html_content += f"<li>{warning}</li>"
                html_content += """
            </ul>
        </div>"""

        html_content += """
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

            # Highlight cumulative metrics
            is_cumulative = self._is_cumulative_metric(stat['metric_name'])
            row_style = ' style="background-color: #f0f8ff;"' if is_cumulative else ''


            # Highlight cumulative metrics
            is_cumulative = self._is_cumulative_metric(stat['metric_name'])
            row_style = ' style="background-color: #f0f8ff;"' if is_cumulative else ''

            html_content += f"""
            <tr{row_style}>
                <td>{stat['name']}{' *' if is_cumulative else ''}</td>
                <td>{stat['total']:,}</td>
                <td>{stat['average']:.1f}</td>
                <td>{stat['max']:,}</td>
                <td>{stat['min']:,}</td>
                <td>{stat['observations']}</td>
                <td>${stat['cost_per_request']:.2f}</td>
                <td>${stat['total_cost']:.2f}</td>
            </tr>"""
            <tr{row_style}>
                <td>{stat['name']}{' *' if is_cumulative else ''}</td>
                <td>{stat['total']:,}</td>
                <td>{stat['average']:.1f}</td>
                <td>{stat['max']:,}</td>
                <td>{stat['min']:,}</td>
                <td>{stat['observations']}</td>
                <td>${stat['cost_per_request']:.2f}</td>
                <td>${stat['total_cost']:.2f}</td>
            </tr>"""

        html_content += f"""
        </table>
        <p style="font-size: 0.9em; color: #666;">
            * Cumulative metrics have been converted from monthly cumulative to daily values
        </p>

        <h2>Balance Requests by Day</h2>"""

        # Find balance request data for daily breakdown
        balance_data = None
        for stat in summary_data:
            if stat['metric_name'] == 'balance-request':
                balance_data = stat
                break

        if balance_data and balance_data.get('computed_series') and balance_data.get('start_date'):
            html_content += """
        <table>
            <tr>
                <th>Date</th>
                <th>Balance Requests</th>
                <th>Daily Cost</th>
            </tr>"""

            # Generate daily breakdown
            start_date_obj = balance_data['start_date']
            computed_series = balance_data['computed_series']
            cost_per_request = balance_data['cost_per_request']

            for i, daily_count in enumerate(computed_series):
                current_date = start_date_obj + timedelta(days=i)
                daily_cost = daily_count * cost_per_request
                date_str = current_date.strftime('%Y-%m-%d (%a)')

                # Highlight weekends or high usage days
                row_style = ''
                if current_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
                    row_style = ' style="background-color: #f9f9f9;"'
                elif daily_count > balance_data['average'] * 1.5:  # High usage days
                    row_style = ' style="background-color: #fff3cd;"'

                html_content += f"""
                <tr{row_style}>
                    <td>{date_str}</td>
                    <td>{daily_count:,}</td>
                    <td>${daily_cost:.2f}</td>
                </tr>"""

            html_content += """
        </table>
        <p style="font-size: 0.9em; color: #666;">
            Weekend days are highlighted in light gray. High usage days (>1.5x average) are highlighted in yellow.
        </p>"""
        else:
            html_content += """
            <p style="color: #dc3545;">No balance request data available for daily breakdown.</p>"""

        html_content += f"""
        <h2>Totals</h2>
        <table>
            <tr><td><strong>Total API Requests</strong></td><td>{total_requests:,}</td></tr>
            <tr><td><strong>Total Estimated Cost</strong></td><td>${total_cost:.2f}</td></tr>
            <tr><td><strong>Average Daily Cost</strong></td><td>${(total_cost / max(1, summary_data[0]['observations']) if summary_data else 0):.2f}</td></tr>
        </table>
        </table>
        <p style="font-size: 0.9em; color: #666;">
            * Cumulative metrics have been converted from monthly cumulative to daily values
        </p>

        <h2>Balance Requests by Day</h2>"""

        # Find balance request data for daily breakdown
        balance_data = None
        for stat in summary_data:
            if stat['metric_name'] == 'balance-request':
                balance_data = stat
                break

        if balance_data and balance_data.get('computed_series') and balance_data.get('start_date'):
            html_content += """
        <table>
            <tr>
                <th>Date</th>
                <th>Balance Requests</th>
                <th>Daily Cost</th>
            </tr>"""

            # Generate daily breakdown
            start_date_obj = balance_data['start_date']
            computed_series = balance_data['computed_series']
            cost_per_request = balance_data['cost_per_request']

            for i, daily_count in enumerate(computed_series):
                current_date = start_date_obj + timedelta(days=i)
                daily_cost = daily_count * cost_per_request
                date_str = current_date.strftime('%Y-%m-%d (%a)')

                # Highlight weekends or high usage days
                row_style = ''
                if current_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
                    row_style = ' style="background-color: #f9f9f9;"'
                elif daily_count > balance_data['average'] * 1.5:  # High usage days
                    row_style = ' style="background-color: #fff3cd;"'

                html_content += f"""
                <tr{row_style}>
                    <td>{date_str}</td>
                    <td>{daily_count:,}</td>
                    <td>${daily_cost:.2f}</td>
                </tr>"""

            html_content += """
        </table>
        <p style="font-size: 0.9em; color: #666;">
            Weekend days are highlighted in light gray. High usage days (>1.5x average) are highlighted in yellow.
        </p>"""
        else:
            html_content += """
            <p style="color: #dc3545;">No balance request data available for daily breakdown.</p>"""

        html_content += f"""
        <h2>Totals</h2>
        <table>
            <tr><td><strong>Total API Requests</strong></td><td>{total_requests:,}</td></tr>
            <tr><td><strong>Total Estimated Cost</strong></td><td>${total_cost:.2f}</td></tr>
            <tr><td><strong>Average Daily Cost</strong></td><td>${(total_cost / max(1, summary_data[0]['observations']) if summary_data else 0):.2f}</td></tr>
        </table>
"""

        html_content += """
</body>
</html>"""

        html_content += """
</body>
</html>"""

        return html_content
