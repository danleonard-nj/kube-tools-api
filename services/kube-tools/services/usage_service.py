from datetime import datetime, timedelta

import pandas as pd
from framework.configuration.configuration import Configuration
from framework.logger.providers import get_logger

from clients.azure_gateway_client import AzureGatewayClient
from clients.email_gateway_client import EmailGatewayClient
from domain.usage import ReportDateRange
from services.event_service import EventService

logger = get_logger(__name__)


def element_at(_list, index):
    try:
        return _list[index]
    except:
        return None


class UsageService:
    def __init__(
        self,
        configuration: Configuration,
        email_client: EmailGatewayClient,
        azure_client: AzureGatewayClient,
        event_service: EventService
    ):
        self.__email_client = email_client
        self.__azure_client = azure_client
        self.__event_service = event_service

        self.__recipient = configuration.azure_usage.get('recipient')

    def __format_date(self, date):
        return date.strftime('%Y-%m-%d')

    async def send_cost_management_report(
        self,
        range_key: str
    ) -> dict:
        logger.info(f'Generating usage report')

        start_date, end_date = self.__get_date_range(
            range_key=range_key)

        logger.info(f'Range: {start_date} to {end_date}')

        content = await self.__azure_client.get_cost_management_data(
            start_date=start_date,
            end_date=end_date)

        data = content.get('data')

        df = pd.DataFrame(data)[[
            'Cost',
            'CostUSD',
            'Currency',
            'Product'
        ]]

        df = df.groupby(by=[
            'Product', 'Currency'],
            as_index=False).sum()

        df = df.sort_values(
            by='Cost',
            ascending=False)

        table = df.to_dict(
            orient='records')

        logger.info('Sending datatable email gateway request')

        event_request, endpoint = self.__email_client.get_datatable_email_request(
            recipient=self.__recipient,
            subject=f'Azure Usage: {range_key}',
            data=table)

        await self.__event_service.dispatch_email_event(
            endpoint=endpoint,
            message=event_request.to_dict())

        return {'table': table}

    def __get_date_range(
        self,
        range_key: str
    ):
        logger.info(f"Parsing range for date range type: '{range_key}'")
        now = datetime.utcnow()

        if range_key is None:
            logger.info(f'Returning default report date range')
            return (
                self.__format_date(now),
                self.__format_date(now)
            )

        if range_key.startswith(ReportDateRange.LastNDays):
            days = element_at(range_key.split('_'), 1)

            if days is None:
                raise Exception("Range key must be in the format 'days_n'")
            if not days.isdigit():
                raise Exception("Range day parameter is not of type 'int'")

            return (
                self.__format_date(now - timedelta(days=int(days))),
                self.__format_date(now)
            )

        if range_key == ReportDateRange.MonthToDate:
            start = datetime(
                year=now.year,
                month=now.month,
                day=1)

            return (
                self.__format_date(start),
                self.__format_date(now)
            )

        if range_key == ReportDateRange.YearToDate:
            start = datetime(
                year=now.year,
                month=1,
                day=1)

            return (
                self.__format_date(start),
                self.__format_date(now)
            )

        raise Exception(f"'{range_key}' is not a valid report date range key")
