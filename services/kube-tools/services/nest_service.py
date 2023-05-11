import asyncio
import hashlib
import json
import threading
import uuid
from datetime import datetime, timedelta
from datetime import datetime, timedelta
from time import time
from typing import Any, Callable, Dict, List, Tuple

from framework.clients.cache_client import CacheClientAsync
from framework.concurrency import TaskCollection
from framework.configuration import Configuration
from framework.crypto.hashing import md5, sha256
from framework.logger import get_logger
from framework.utilities.pinq import first
from pymongo.results import DeleteResult

from clients.email_gateway_client import EmailGatewayClient
from clients.email_gateway_client import EmailGatewayClient
from clients.nest_client import NestClient
from data.nest_repository import NestDeviceRepository, NestSensorRepository
from domain.cache import CacheKey
from domain.nest import NestSensorData, NestSensorDevice, NestThermostat
from domain.rest import NestSensorDataRequest
from services.event_service import EventService
from framework.serialization import Serializable
import pandas as pd

logger = get_logger(__name__)


class NestSensorDataQueryResult(Serializable):
    def __init__(
        self,
        device_id: str,
        data: List[NestSensorData]
    ):
        self.device_id = device_id
        self.data = data


class ThreadTask:
    def __init__(
        self,
        func,
        args=[],
        kwargs={}
    ):
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def invoke(
        self
    ) -> Any:
        return self.func(
            *self.args,
            **self.kwargs
        )


class ThreadCollection:
    def __init__(
        self,
        tasks: List[Callable] = []
    ):
        self.__tasks = tasks

    def add_task(
        self,
        func: Callable,
        *args,
        **kwargs
    ):
        task = ThreadTask(
            func=func,
            args=args,
            kwargs=kwargs)

        self.__tasks.append(task)

    def run(
        self,
        wait: bool = True
    ) -> Dict[int, Any]:

        threads = list()

        results = {
            x: list() for x in
            range(len(self.__tasks))
        }

        def task_wrapper(index, task: ThreadTask):
            logger.info(f'Starting task thread: {index}')
            try:
                logger.info(f'Invoking thread func for task: {index}')

                result = task.invoke()

                results[index].append(result)
            except Exception as ex:
                results[index].append(ex)

        for index in range(len(self.__tasks)):
            logger.info(f'Arranging task thread: {index}')
            task = self.__tasks[index]
            thread = threading.Thread(
                target=task_wrapper,
                args=(index, task))
            threads.append(thread)

        for thread in threads:
            logger.info(f'Starting task thread')
            thread.start()

        if wait:
            # Only wait on threads to complete if
            # wait param is true otherwise fire
            # and forget
            for thread in threads:
                thread.join()

        logger.info(f'Task threads completed')
        return results


DEFAULT_PURGE_DAYS = 90


def get_timestamp():
    return round(time())


def get_key(*args, **kwargs):
    digest = hashlib.md5(json.dumps(
        kwargs,
        default=str).encode())

    return str(uuid.UUID(digest.hexdigest()))


class NestService:
    def __init__(
        self,
        configuration: Configuration,
        nest_client: NestClient,
        sensor_repository: NestSensorRepository,
        device_repository: NestDeviceRepository,
        event_service: EventService,
        email_gateway: EmailGatewayClient,
        cache_client: CacheClientAsync
    ):
        self.__thermostat_id = configuration.nest.get(
            'thermostat_id')
        self.__purge_days = configuration.nest.get(
            'purge_days', DEFAULT_PURGE_DAYS)
        self.__purge_days = configuration.nest.get(
            'purge_days', DEFAULT_PURGE_DAYS)

        self.__nest_client = nest_client
        self.__sensor_repository = sensor_repository
        self.__device_repository = device_repository
        self.__event_service = event_service
        self.__email_gateway = email_gateway
        self.__cache_client = cache_client

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
            timestamp = get_timestamp())

        logger.info(f'Capturing sensor data: {sensor_data}')

        result=await self.__sensor_repository.insert(
            document = sensor_data.to_dict())

        logger.info(f'Success: {result.acknowledged}')

        return sensor_data

    async def purge_sensor_data(
        self
    ):
        logger.info(f'Purging sensor data: {self.__purge_days} days back')

        cutoff_date=datetime.utcnow() - timedelta(
            days = self.__purge_days)

        cutoff_timestamp=int(cutoff_date.timestamp())
        logger.info(f'Cutoff timestamp: {cutoff_timestamp}')

        result=await self.__sensor_repository.collection.delete_many({
            'timestamp': {
                '$lte': cutoff_timestamp
            }
        })

        logger.info(f'Deleted: {result.deleted_count}')

        email_request, endpoint=self.__email_gateway.get_email_request(
            recipient = 'dcl525@gmail.com',
            subject = 'Sensor Data Service',
            body = self.__get_email_message_body(
                cutoff_date=cutoff_date,
                deleted_count=result.deleted_count
            ))

        await self.__event_service.dispatch_email_event(
            endpoint = endpoint,
            message = email_request.to_dict())

        return {
            'deleted': result.deleted_count
        }

    async def get_sensor_data(
        self,
        start_timestamp: int
    ) -> List[Dict[str, List[NestSensorData]]]:

        logger.info(f'Get sensor data: {start_timestamp}')
        device_entities = await self.__device_repository.get_all()

        devices = [
            NestSensorDevice.from_entity(data=entity)
            for entity in device_entities
        ]

        results = list()

        for device in devices:
            logger.info(f'Fetching data for device: {device.device_id}')
            entities = await self.__sensor_repository.get_by_device(
                device_id=device.device_id,
                start_timestamp=start_timestamp)

            data = [NestSensorData.from_entity(data=entity)
                    for entity in entities]

            results.append({
                'device_id': device.device_id,
                'data': data
            })

        return results

    async def get_grouped_sensor_data(
        self,
        start_timestamp: int
    ):
        data = await self.get_sensor_data(
            start_timestamp=start_timestamp)

        with open(r'C:\temp\sensor_data.json', 'w') as file:
            for device in data:
                device['data'] = [x.to_dict() for x in device['data']]

            file.write(json.dumps(data, default=str, indent=True))

        # tasks = ThreadCollection()
        tasks = TaskCollection()

        # for device in data:
        #     # Enqueue task thread to transform sensor
        #     # data in parallel (bound by compute not
        #     # I/O)
        #     tasks.add_task(
        #         func=self.group_device_sensor_data,
        #         device=device)

        # results = tasks.run()

        for device in data:
            device_id = device.get('device_id')
            entities = device.get('data')

            sensor_data = [
                NestSensorData.from_entity(data=entity)
                for entity in entities
            ]

            tasks.add_task(self.group_device_sensor_data(
                device_id=device_id,
                sensor_data=sensor_data))

        results = await tasks.run()

        return results

    async def group_device_sensor_data(
        self,
        device_id: str,
        sensor_data: List[NestSensorData]
    ) -> NestSensorDataQueryResult:

        df = self.__to_dataframe(
            sensor_data=sensor_data)

        logger.info(f'Uncollapsed row count: {device_id}: {len(sensor_data)}')

        grouped = df.groupby([df['timestamp'].dt.minute]).first()

        logger.info(f'Collapsed row count: {device_id}: {len(grouped)}')

        return NestSensorDataQueryResult(
            device_id=device_id,
            data=grouped.to_dict(orient='records'))

    def __to_dataframe(
        self,
        sensor_data: List[NestSensorData]
    ):
        data = list()
        for entry in sensor_data:
            data.append({
                'key': entry.key,
                'degrees_celsius': entry.degrees_celsius,
                'degrees_fahrenheit': entry.degrees_fahrenheit,
                'humidity_percent': entry.humidity_percent,
                'timestamp': entry.get_timestamp_datetime()
            })

        return pd.DataFrame(data)

    def __get_key(
        self,
        **kwargs
    ):
        return md5(json.dumps(kwargs))

    async def get_cached_group_sensor_data(
        self,
        device_id: str,
        key: str
    ):
        cache_key = CacheKey.nest_device_grouped_sensor_data(
            device_id=device_id,
            key=key)

        logger.info(f'Get device sensor data: {cache_key}')

        data = await self.__cache_client.get_json(
            key=cache_key)

    def __get_email_message_body(
        self,
        cutoff_date: datetime,
        deleted_count
    ) -> str:
        msg = 'Sensor Data Service'
        msg += ''
        msg += f'Cutoff Date: {cutoff_date.isoformat()}'
        msg += f'Count: {deleted_count}'
