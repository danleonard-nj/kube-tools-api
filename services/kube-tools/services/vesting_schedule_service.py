import asyncio
from datetime import datetime
import pandas as pd
import yfinance as yf
from dateutil import parser

from data.vesting_schedule_repository import VestingScheduleRepository
from framework.caching.memory_cache import MemoryCache
from framework.serialization import Serializable
from framework.clients.cache_client import CacheClientAsync
from framework.logger import get_logger

from domain.cache import CacheKey

logger = get_logger(__name__)


def format_currency(value):
    return '${:0,.2f}'.format(value)


class VestingScheduleResponse(Serializable):
    def __init__(
        self,
        schedule: list[dict],
        subtotal: float | int,
        total: float | int,
        stock_price: float | int,
        refresh_date: str | datetime | None
    ):
        self.subtotal = subtotal
        self.schedule = schedule
        self.total = total
        self.stock_price = stock_price
        self.refresh_date = str(refresh_date)

    @staticmethod
    def from_dict(
        data
    ):
        return VestingScheduleResponse(
            subtotal=data.get('subtotal'),
            total=data.get('total'),
            schedule=data.get('schedule'),
            stock_price=data.get('stock_price'),
            refresh_date=data.get('refresh_date'))


class VestingScheduleService:
    def __init__(
        self,
        vesting_schedule: VestingScheduleRepository,
        memory_cache: MemoryCache,
        cache_client: CacheClientAsync
    ):
        self.__vesting_schedule = vesting_schedule
        self.__memory_cache = memory_cache
        self.__cache_client = cache_client

    async def get_db_schedule(
        self
    ):
        data = await self.__vesting_schedule.get_schedule()

        df = pd.DataFrame(data)

        return df

    async def fetch_stock_price(
        self
    ):
        key = CacheKey.vesting_shedule_stock_price()
        logger.info(f'Fetching stock price from cache: {key}')

        cached_stock_price = await self.__cache_client.get_cache(
            key=CacheKey.vesting_shedule_stock_price())

        if cached_stock_price is not None:
            logger.info(f'Using cached stock price: {cached_stock_price}')
            return cached_stock_price

        logger.info(f'Fetching stock price')
        stock = yf.Ticker('CVNA')
        data = stock.history(period='1d')

        if data.empty:
            return None

        latest_price = data['Close'].iloc[-1]

        # Cache the stock price for 15 mins
        asyncio.create_task(
            self.__cache_client.set_cache(key, latest_price, ttl=15))

        return latest_price

    async def get_vesting_schedule(
        self,
        date: datetime | str | None
    ) -> Serializable:

        cached = (await self.__cache_client.get_json(
            key=CacheKey.vesting_shedule(date))) or dict()

        cached_response = cached.get('response')
        refresh_date = cached.get(
            'refresh_date', datetime.utcnow().isoformat())

        if cached_response is not None:
            logger.info(
                f'Using cached response from: {refresh_date}')
            return cached_response

        df = await self.get_db_schedule()

        logger.info(f'Schedule df: {df}')

        # Fetch the current stock price
        print('Getting stock price')
        stock_price = await self.fetch_stock_price()

        print(f'Stock price: {stock_price}')

        stock_price = float(stock_price)

        # Calculate the vested amount in a new column
        logger.info(f'Calculating projected vested amount')
        df['Amount'] = df.apply(lambda row: format_currency(
            row['Vested'] * stock_price), axis=1)

        def get_days_remaining(row):
            return (row['VestDate'] - datetime.utcnow()).days

        logger.info(f'Calculating the remaining time to vest')
        df['DaysRemaining'] = df.apply(
            lambda row: get_days_remaining(row), axis=1)

        total = df['Amount'].max()

        # Filter by from date if provided
        if date is not None:
            logger.info(f'Filtering by date: {date}')

            # Parse the date if it's a string
            if isinstance(date, str):
                logger.info(f'Parsing date string: {date}')
                date = parser.parse(date)

            # Filter the schedule dataframe
            logger.info(f'Rows pre-filter: {len(df)}')

            df = df[df['VestDate'] <= date]
            logger.info(f'Rows post-filter: {len(df)}')

        # Get the subtotal vested amount from the
        # filtered dataframe
        subtotal = df['Amount'].max()
        schedule = df.to_dict(orient='records')

        logger.info(f'Total: {total}')
        logger.info(f'Subtotal: {subtotal}')
        logger.info(f'Schedule: {schedule}')

        response = VestingScheduleResponse(
            schedule=schedule,
            subtotal=subtotal,
            total=total,
            stock_price=stock_price,
            refresh_date=refresh_date)

        # Cache the entire calculated vesting schedule
        # for 5 mins
        cache_data = dict(
            response=response.to_dict(),
            refresh_date=datetime.utcnow().isoformat()
        )

        asyncio.create_task(self.__cache_client.set_json(
            key=CacheKey.vesting_shedule(date),
            value=cache_data,
            ttl=5))

        return response
