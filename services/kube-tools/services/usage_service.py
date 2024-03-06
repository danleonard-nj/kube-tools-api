from datetime import datetime, timedelta

import pandas as pd
from clients.azure_gateway_client import AzureGatewayClient
from clients.email_gateway_client import EmailGatewayClient
from domain.exceptions import UsageRangeException
from domain.usage import (REPORT_COLUMNS, REPORT_EMAIL_SUBJECT,
                          REPORT_GROUP_KEYS, REPORT_SORT_KEY, ReportDateRange,
                          format_date)
from framework.configuration.configuration import Configuration
from framework.logger.providers import get_logger
from services.event_service import EventService
from utilities.utils import element_at

logger = get_logger(__name__)


class UsageService:
    def __init__(
        self,
        configuration: Configuration,
        email_client: EmailGatewayClient,
        azure_client: AzureGatewayClient,
        event_service: EventService
    ):
        self._email_client = email_client
        self._azure_client = azure_client
        self._event_service = event_service

        self._recipient = configuration.azure_usage.get('recipient')

    async def send_cost_management_report(
        self,
        range_key: str
    ) -> dict:
        logger.info(f'Generating usage report')

        start_date, end_date = self._get_date_range(
            range_key=range_key)

        logger.info(f'Range: {start_date} to {end_date}')

        content = await self._azure_client.get_cost_management_data(
            start_date=start_date,
            end_date=end_date)

        data = content.get('data')

        df = pd.DataFrame(data)[REPORT_COLUMNS]

        df = (df
              .groupby(
                  by=REPORT_GROUP_KEYS,
                  as_index=False)
              .sum())

        df = df.sort_values(
            by=REPORT_SORT_KEY,
            ascending=False)

        table = df.to_dict(
            orient='records')

        logger.info('Sending datatable email gateway request')

        event_request, endpoint = self._email_client.get_datatable_email_request(
            recipient=self._recipient,
            subject=f'{REPORT_EMAIL_SUBJECT}: {range_key}',
            data=table)

        await self._event_service.dispatch_email_event(
            endpoint=endpoint,
            message=event_request.to_dict())

        return {
            'table': table
        }

    def _get_date_range(
        self,
        range_key: str
    ):
        logger.info(f"Parsing range for date range type: '{range_key}'")
        now = datetime.utcnow()

        if range_key is None:
            logger.info(f'Returning default report date range')
            return (
                format_date(now),
                format_date(now)
            )

        if range_key.startswith(ReportDateRange.LastNDays):
            days = element_at(range_key.split('_'), 1)

            if days is None:
                raise UsageRangeException(
                    "Range key must be in the format 'days_n'")
            if not days.isdigit():
                raise UsageRangeException(
                    "Range day parameter is not of type 'int'")

            return (
                format_date(now - timedelta(days=int(days))),
                format_date(now)
            )

        if range_key == ReportDateRange.MonthToDate:
            start = datetime(
                year=now.year,
                month=now.month,
                day=1)

            return (
                format_date(start),
                format_date(now)
            )

        if range_key == ReportDateRange.YearToDate:
            start = datetime(
                year=now.year,
                month=1,
                day=1)

            return (
                format_date(start),
                format_date(now)
            )

        raise Exception(f"'{range_key}' is not a valid report date range key")
