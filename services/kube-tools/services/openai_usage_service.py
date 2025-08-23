
import asyncio
import logging
from framework.logger import get_logger
from framework.configuration import Configuration
import httpx
from datetime import datetime, timedelta, date
from collections import defaultdict
from typing import Dict, List, Any

from clients.sib_client import SendInBlueClient
from models.openai_config import OpenAIConfig
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

logger = get_logger(__name__)


class OpenAiUsageService:
    def __init__(
        self,
        config: OpenAIConfig,
        sib_client: SendInBlueClient,
        http_client: httpx.AsyncClient
    ):
        self._api_key = config.api_key
        self._http_client = http_client
        self._sib_client = sib_client

    @retry(
        retry=retry_if_exception(
            lambda e: isinstance(e, httpx.RequestError)
            or (
                isinstance(e, httpx.HTTPStatusError)
                and e.response is not None
                and e.response.status_code == 429
            )
        ),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=1, min=3, max=60),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def _get_with_retry(self, url: str, headers: dict = None, params: dict = None) -> httpx.Response:
        """Perform an HTTP GET with retries for transient errors (429 and network errors).

        Uses tenacity to retry on httpx.RequestError and on HTTP 429 responses.
        """
        try:
            resp = await self._http_client.get(url, headers=headers, params=params)
        except httpx.RequestError as ex:
            # Let tenacity see the exception and decide to retry
            raise

        # If we receive a 429, raise an HTTPStatusError so tenacity will retry based on the predicate
        if resp.status_code == 429:
            logger.warning(f"Received 429 from {url}. Response headers: {resp.headers}")
            # raise an HTTPStatusError that tenacity's predicate will recognize
            raise httpx.HTTPStatusError("429 Too Many Requests", request=resp.request, response=resp)

        # For other status codes, raise for status to preserve existing behavior
        resp.raise_for_status()
        return resp

    async def _fetch_usage_data(
        self,
        start_date: datetime,
        end_date: datetime = None
    ) -> List[Dict[str, Any]]:
        end_date = end_date or date.today()

        headers = {
            'Authorization': f'Bearer {self._api_key}'
        }

        records = []

        d = start_date
        while d <= end_date:
            logger.info(f'Fetching data for {d.isoformat()}')
            resp = await self._get_with_retry(
                "https://api.openai.com/v1/usage",
                headers=headers,
                params={"date": d.isoformat()}
            )
            usage_response = resp.json()
            for entry in usage_response.get("data", []):
                records.append(entry)
            d += timedelta(days=1)
            await asyncio.sleep(3)

        return records

    def _aggregate_usage_data(self, usage_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate usage data by model and date for better reporting."""
        daily_summary = defaultdict(lambda: {
            'total_requests': 0,
            'total_context_tokens': 0,
            'total_generated_tokens': 0,
            'models': defaultdict(lambda: {
                'requests': 0,
                'context_tokens': 0,
                'generated_tokens': 0
            })
        })

        model_summary = defaultdict(lambda: {
            'requests': 0,
            'context_tokens': 0,
            'generated_tokens': 0,
            'total_tokens': 0
        })

        total_summary = {
            'total_requests': 0,
            'total_context_tokens': 0,
            'total_generated_tokens': 0,
            'total_tokens': 0,
            'unique_models': set()
        }

        for entry in usage_data:
            # Convert timestamp to date
            timestamp = entry.get('aggregation_timestamp', 0)
            entry_date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')

            model = entry.get('snapshot_id', 'Unknown Model')
            requests = entry.get('n_requests', 0)
            context_tokens = entry.get('n_context_tokens_total', 0)
            generated_tokens = entry.get('n_generated_tokens_total', 0)

            # Daily aggregation
            daily_summary[entry_date]['total_requests'] += requests
            daily_summary[entry_date]['total_context_tokens'] += context_tokens
            daily_summary[entry_date]['total_generated_tokens'] += generated_tokens

            daily_summary[entry_date]['models'][model]['requests'] += requests
            daily_summary[entry_date]['models'][model]['context_tokens'] += context_tokens
            daily_summary[entry_date]['models'][model]['generated_tokens'] += generated_tokens

            # Model aggregation
            model_summary[model]['requests'] += requests
            model_summary[model]['context_tokens'] += context_tokens
            model_summary[model]['generated_tokens'] += generated_tokens
            model_summary[model]['total_tokens'] += context_tokens + generated_tokens

            # Total aggregation
            total_summary['total_requests'] += requests
            total_summary['total_context_tokens'] += context_tokens
            total_summary['total_generated_tokens'] += generated_tokens
            total_summary['total_tokens'] += context_tokens + generated_tokens
            total_summary['unique_models'].add(model)

        return {
            'daily': dict(daily_summary),
            'models': dict(model_summary),
            'total': total_summary
        }

    def _generate_html_report(self, aggregated_data: Dict[str, Any], start_date: date, end_date: date) -> str:
        """Generate a clean, professional HTML report with proper responsive design."""
        total = aggregated_data['total']
        models = aggregated_data['models']
        daily = aggregated_data['daily']

        # Format numbers with commas
        def format_number(num):
            return f"{num:,}"

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                * {{
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }}
                
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    background-color: #f9f9f9;
                    padding: 20px;
                }}
                
                .container {{
                    max-width: 900px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 6px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    overflow: hidden;
                }}
                
                .header {{
                    background: linear-gradient(135deg, #4a5568 0%, #2d3748 100%);
                    color: white;
                    padding: 30px 20px;
                    text-align: center;
                }}
                
                .header h1 {{
                    font-size: 28px;
                    font-weight: 600;
                    margin-bottom: 8px;
                }}
                
                .header p {{
                    opacity: 0.9;
                    font-size: 15px;
                }}
                
                .content {{
                    padding: 30px 20px;
                }}
                
                /* Summary Cards Grid */
                .summary-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 15px;
                    margin-bottom: 30px;
                }}
                
                .summary-card {{
                    background: #f8f9fa;
                    border: 1px solid #e2e8f0;
                    padding: 20px;
                    border-radius: 6px;
                    transition: transform 0.2s, box-shadow 0.2s;
                }}
                
                .summary-card:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                }}
                
                .summary-card h3 {{
                    color: #718096;
                    font-size: 12px;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    font-weight: 600;
                    margin-bottom: 8px;
                }}
                
                .summary-card .value {{
                    font-size: 24px;
                    font-weight: 700;
                    color: #2d3748;
                }}
                
                /* Section Styling */
                .section {{
                    margin-bottom: 30px;
                }}
                
                .section h2 {{
                    color: #4a5568;
                    font-size: 20px;
                    margin-bottom: 15px;
                    padding-bottom: 8px;
                    border-bottom: 2px solid #e2e8f0;
                    font-weight: 600;
                }}
                
                .section h3 {{
                    color: #4a5568;
                    font-size: 16px;
                    margin: 20px 0 10px 0;
                    font-weight: 500;
                }}
                
                /* Table Container for Horizontal Scroll */
                .table-container {{
                    width: 100%;
                    overflow-x: auto;
                    -webkit-overflow-scrolling: touch; /* Smooth scrolling on iOS */
                    margin-bottom: 20px;
                    border: 1px solid #e2e8f0;
                    border-radius: 4px;
                }}
                
                /* Scroll indicator for mobile */
                .table-container::-webkit-scrollbar {{
                    height: 8px;
                }}
                
                .table-container::-webkit-scrollbar-track {{
                    background: #f1f1f1;
                }}
                
                .table-container::-webkit-scrollbar-thumb {{
                    background: #888;
                    border-radius: 4px;
                }}
                
                .table-container::-webkit-scrollbar-thumb:hover {{
                    background: #555;
                }}
                
                /* Table Styling */
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    min-width: 600px; /* Ensures table maintains minimum width */
                }}
                
                th, td {{
                    padding: 12px;
                    text-align: left;
                    border-bottom: 1px solid #e2e8f0;
                }}
                
                th {{
                    background-color: #f8f9fa;
                    font-weight: 600;
                    color: #4a5568;
                    font-size: 13px;
                    text-transform: uppercase;
                    letter-spacing: 0.3px;
                    position: sticky;
                    top: 0;
                    z-index: 10;
                }}
                
                tr:hover {{
                    background-color: #f8f9fa;
                }}
                
                td {{
                    font-size: 14px;
                    color: #2d3748;
                }}
                
                /* Model tag styling */
                .model-tag {{
                    display: inline-block;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 4px 10px;
                    border-radius: 12px;
                    font-size: 11px;
                    font-weight: 600;
                    letter-spacing: 0.3px;
                }}
                
                /* Footer */
                .footer {{
                    background: #f8f9fa;
                    padding: 20px;
                    text-align: center;
                    color: #718096;
                    font-size: 13px;
                    border-top: 1px solid #e2e8f0;
                }}
                
                .footer p {{
                    margin: 4px 0;
                }}
                
                /* Mobile Responsive Styles */
                @media screen and (max-width: 768px) {{
                    body {{
                        padding: 10px;
                    }}
                    
                    .header {{
                        padding: 20px 15px;
                    }}
                    
                    .header h1 {{
                        font-size: 22px;
                    }}
                    
                    .header p {{
                        font-size: 14px;
                    }}
                    
                    .content {{
                        padding: 20px 15px;
                    }}
                    
                    .summary-grid {{
                        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                        gap: 10px;
                    }}
                    
                    .summary-card {{
                        padding: 15px;
                    }}
                    
                    .summary-card h3 {{
                        font-size: 11px;
                    }}
                    
                    .summary-card .value {{
                        font-size: 20px;
                    }}
                    
                    .section h2 {{
                        font-size: 18px;
                    }}
                    
                    /* Add scroll hint for tables on mobile */
                    .table-container::after {{
                        content: '→ Scroll for more';
                        position: absolute;
                        top: 10px;
                        right: 10px;
                        background: rgba(0,0,0,0.7);
                        color: white;
                        padding: 4px 8px;
                        border-radius: 4px;
                        font-size: 11px;
                        pointer-events: none;
                        opacity: 0.8;
                    }}
                    
                    .table-container {{
                        position: relative;
                    }}
                    
                    th, td {{
                        padding: 8px;
                        font-size: 12px;
                    }}
                }}
                
                @media screen and (max-width: 480px) {{
                    .summary-grid {{
                        grid-template-columns: 1fr;
                    }}
                    
                    .header h1 {{
                        font-size: 20px;
                    }}
                    
                    table {{
                        min-width: 500px;
                    }}
                }}
                
                /* Print styles */
                @media print {{
                    body {{
                        background: white;
                    }}
                    
                    .container {{
                        box-shadow: none;
                    }}
                    
                    .table-container {{
                        overflow: visible;
                    }}
                    
                    table {{
                        width: 100%;
                        min-width: auto;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>OpenAI API Usage Report</h1>
                    <p>{start_date.strftime('%B %d, %Y')} - {end_date.strftime('%B %d, %Y')}</p>
                </div>
                
                <div class="content">
                    <div class="summary-grid">
                        <div class="summary-card">
                            <h3>Total Requests</h3>
                            <div class="value">{format_number(total['total_requests'])}</div>
                        </div>
                        <div class="summary-card">
                            <h3>Context Tokens</h3>
                            <div class="value">{format_number(total['total_context_tokens'])}</div>
                        </div>
                        <div class="summary-card">
                            <h3>Generated Tokens</h3>
                            <div class="value">{format_number(total['total_generated_tokens'])}</div>
                        </div>
                        <div class="summary-card">
                            <h3>Total Tokens</h3>
                            <div class="value">{format_number(total['total_tokens'])}</div>
                        </div>
                    </div>
                    
                    <div class="section">
                        <h2>Usage by Model</h2>
                        <div class="table-container">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Model</th>
                                        <th>Requests</th>
                                        <th>Context Tokens</th>
                                        <th>Generated Tokens</th>
                                        <th>Total Tokens</th>
                                    </tr>
                                </thead>
                                <tbody>
        """

        for model, data in sorted(models.items(), key=lambda x: x[1]['total_tokens'], reverse=True):
            html += f"""
                                <tr>
                                    <td><span class="model-tag">{model}</span></td>
                                    <td>{format_number(data['requests'])}</td>
                                    <td>{format_number(data['context_tokens'])}</td>
                                    <td>{format_number(data['generated_tokens'])}</td>
                                    <td>{format_number(data['total_tokens'])}</td>
                                </tr>
            """

        html += """
                                </tbody>
                            </table>
                        </div>
                    </div>
                    
                    <div class="section">
                        <h2>Daily Usage Summary</h2>
                        <div class="table-container">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Date</th>
                                        <th>Requests</th>
                                        <th>Context Tokens</th>
                                        <th>Generated Tokens</th>
                                        <th>Total Tokens</th>
                                    </tr>
                                </thead>
                                <tbody>
        """

        for date_str in sorted(daily.keys(), reverse=True):
            day_data = daily[date_str]
            total_tokens = day_data['total_context_tokens'] + day_data['total_generated_tokens']
            html += f"""
                                <tr>
                                    <td>{datetime.strptime(date_str, '%Y-%m-%d').strftime('%b %d, %Y')}</td>
                                    <td>{format_number(day_data['total_requests'])}</td>
                                    <td>{format_number(day_data['total_context_tokens'])}</td>
                                    <td>{format_number(day_data['total_generated_tokens'])}</td>
                                    <td>{format_number(total_tokens)}</td>
                                </tr>
            """

        html += """
                                </tbody>
                            </table>
                        </div>
                    </div>
                    
                    <div class="section">
                        <h2>Model Usage by Day</h2>
        """

        # Add model breakdown by day
        for date_str in sorted(daily.keys(), reverse=True):  # Limit to last 7 days for email size
            day_data = daily[date_str]
            if day_data['models']:
                html += f"""
                        <h3>{datetime.strptime(date_str, '%Y-%m-%d').strftime('%B %d, %Y')}</h3>
                        <div class="table-container">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Model</th>
                                        <th>Requests</th>
                                        <th>Context Tokens</th>
                                        <th>Generated Tokens</th>
                                        <th>Total Tokens</th>
                                    </tr>
                                </thead>
                                <tbody>
                """

                for model, model_data in sorted(day_data['models'].items(), key=lambda x: x[1]['context_tokens'] + x[1]['generated_tokens'], reverse=True):
                    total_model_tokens = model_data['context_tokens'] + model_data['generated_tokens']
                    html += f"""
                                <tr>
                                    <td><span class="model-tag">{model}</span></td>
                                    <td>{format_number(model_data['requests'])}</td>
                                    <td>{format_number(model_data['context_tokens'])}</td>
                                    <td>{format_number(model_data['generated_tokens'])}</td>
                                    <td>{format_number(total_model_tokens)}</td>
                                </tr>
                    """

                html += """
                                </tbody>
                            </table>
                        </div>
                """

        html += f"""
                    </div>
                </div>
                
                <div class="footer">
                    <p><strong>Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</strong></p>
                    <p>Report covers {len(daily)} days with {len(models)} unique models</p>
                </div>
            </div>
        </body>
        </html>
        """

        return html

    async def send_report(
        self,
        days_back: int = 30,
        recipients: List[str] = None
    ):
        """Generate and send a comprehensive OpenAI usage report."""
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days_back)

        logger.info(f"Generating OpenAI usage report for {start_date} to {end_date}")

        usage_data = await self._fetch_usage_data(start_date, end_date)

        if not usage_data:
            logger.info("No usage data available for the specified period.")
            return

        # Aggregate the data
        aggregated_data = self._aggregate_usage_data(usage_data)

        # Generate HTML report
        html_report = self._generate_html_report(aggregated_data, start_date, end_date)

        # Generate subject with key metrics
        total_requests = aggregated_data['total']['total_requests']
        total_tokens = aggregated_data['total']['total_tokens']
        subject = f"OpenAI Usage Report - {total_requests:,} requests, {total_tokens:,} tokens ({start_date.strftime('%m/%d')} - {end_date.strftime('%m/%d')})"

        # Send the report via SendInBlue
        await self._sib_client.send_email(
            subject=subject,
            html_body=html_report,
            recipient=recipients,
            from_email='me@dan-leonard.com',
            from_name='KubeTools Report Service'
        )

        logger.info(f"OpenAI usage report sent to {len(recipients)} recipients")

        return aggregated_data
