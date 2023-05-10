import uuid
from datetime import datetime, timedelta
from time import time

from framework.configuration import Configuration
from framework.logger import get_logger
from pymongo.results import DeleteResult

from clients.email_gateway_client import EmailGatewayClient
from clients.nest_client import NestClient
from data.nest_repository import NestSensorRepository
from domain.nest import NestSensorData, NestThermostat
from domain.rest import NestSensorDataRequest
from services.event_service import EventService

logger = get_logger(__name__)

DEFAULT_PURGE_DAYS = 90


def get_timestamp():
    return round(time())


class NestService:
    def __init__(
        self,
        configuration: Configuration,
        nest_client: NestClient,
        sensor_repository: NestSensorRepository,
        event_service: EventService,
        email_gateway: EmailGatewayClient
    ):
        self.__thermostat_id = configuration.nest.get(
            'thermostat_id')
        self.__purge_days = configuration.nest.get(
            'purge_days', DEFAULT_PURGE_DAYS)

        self.__nest_client = nest_client
        self.__sensor_repository = sensor_repository
        self.__event_service = event_service
        self.__email_gateway = email_gateway

    async def get_thermostat(
        self
    ) -> NestThermostat:

        data = await self.__nest_client.get_thermostat()

        thermostat = NestThermostat.from_json_object(
            data=data,
            thermostat_id=self.__thermostat_id)

        return thermostat

    async def log_sensor_data(
        self,
        sensor_request: NestSensorDataRequest
    ) -> NestSensorData:

        sensor_data = NestSensorData(
            record_id=str(uuid.uuid4()),
            sensor_id=sensor_request.sensor_id,
            humidity_percent=sensor_request.humidity_percent,
            degrees_celsius=sensor_request.degrees_celsius,
            timestamp=get_timestamp())

        logger.info(f'Capturing sensor data: {sensor_data}')

        result = await self.__sensor_repository.insert(
            document=sensor_data.to_dict())

        logger.info(f'Success: {result.acknowledged}')

        return sensor_data

    async def purge_sensor_data(
        self
    ):
        logger.info(f'Purging sensor data: {self.__purge_days} days back')

        cutoff_date = datetime.utcnow() - timedelta(
            days=self.__purge_days)

        cutoff_timestamp = int(cutoff_date.timestamp())
        logger.info(f'Cutoff timestamp: {cutoff_timestamp}')

        result = await self.__sensor_repository.collection.delete_many({
            'timestamp': {
                '$lte': cutoff_timestamp
            }
        })

        logger.info(f'Deleted: {result.deleted_count}')

        email_request, endpoint = self.__email_gateway.get_email_request(
            recipient='dcl525@gmail.com',
            subject='Sensor Data Service',
            body=self.__get_email_message_body(
                cutoff_date=cutoff_date,
                deleted_count=result.deleted_count
            ))

        await self.__event_service.dispatch_email_event(
            endpoint=endpoint,
            message=email_request.to_dict())

        return {
            'deleted': result.deleted_count
        }

    def __get_email_message_body(
        self,
        cutoff_date: datetime,
        deleted_count
    ) -> str:
        msg = 'Sensor Data Service'
        msg += ''
        msg += f'Cutoff Date: {cutoff_date.isoformat()}'
        msg += f'Count: {deleted_count}'
