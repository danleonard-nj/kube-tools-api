import uuid
from time import time

from framework.configuration import Configuration
from framework.logger import get_logger

from clients.nest_client import NestClient
from data.nest_repository import NestSensorRepository
from domain.nest import NestSensorData, NestThermostat
from domain.rest import NestSensorDataRequest

logger = get_logger(__name__)


class NestService:
    def __init__(
        self,
        configuration: Configuration,
        nest_client: NestClient,
        sensor_repository: NestSensorRepository
    ):
        self.__thermostat_id = configuration.nest.get(
            'thermostat_id')

        self.__nest_client = nest_client
        self.__sensor_repository = sensor_repository

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
            timestamp=int(time()))

        logger.info(f'Capturing sensor data: {sensor_data}')

        result = await self.__sensor_repository.insert(
            document=sensor_data.to_dict())

        logger.info(f'Success: {result.acknowledged}')

        return sensor_data
