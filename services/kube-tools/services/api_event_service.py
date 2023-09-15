import stat
import time
from typing import Dict, List

from framework.logger import get_logger

from data.api_event_repository import ApiEventAlertRepository, ApiEventRepository
from framework.serialization import Serializable

DEFAULT_ALERT_LOOKBACK_HOURS = 1

logger = get_logger(__name__)


class ApiEventAlert(Serializable):
    def __init__(
        self,
        event_id: str,
        key: str,
        endpoint: str,
        status_code: int,
        event_date: int
    ):
        self.event_id = event_id
        self.key = key
        self.endpoint = endpoint
        self.status_code = status_code
        self.event_date = event_date

    @staticmethod
    def from_event(data):
        return ApiEventAlert(
            event_id=data.get('log_id'),
            key=data.get('key'),
            endpoint=data.get('endpoint'),
            status_code=data.get('status_code'),
            event_date=data.get('timestamp'))

    @staticmethod
    def from_entity(data):
        return ApiEventAlert(
            event_id=data.get('event_id'),
            key=data.get('key'),
            endpoint=data.get('endpoint'),
            status_code=data.get('status_code'),
            event_date=data.get('event_date'))


class ApiEventHistoryService:
    def __init__(
        self,
        repository: ApiEventRepository,
        alert_repostory: ApiEventAlertRepository
    ):
        self.__repository = repository
        self.__alert_repository = alert_repostory

    async def poll_event_alerts(
        self,
        hours_back: int | None = None,
    ):

        logger.info(f'Polling for api event alerts: {hours_back} hours back')
        hours_back = hours_back or DEFAULT_ALERT_LOOKBACK_HOURS

        error_event_entities = await self.__repository.collection.find({
            'status_code': {
                '$ne': 200
            }
        })

        error_events = [ApiEventAlert.from_event(e)
                        for e in error_event_entities]

        event_ids = [e.event_id for e in error_events]

        cutoff_timestamp = int(time.time()) - (hours_back * 60 * 60)

        api_events = await self.__repository.collection.find({
            'timestamp': {
                '$gte': cutoff_timestamp
            },
            'log_id': {
                '$nin': event_ids
            }
        })

        if not any(api_events):
            logger.info('No new api events found')
            return []

        logger.info(f'Found {len(api_events)} new api events')

        api_events = [ApiEventAlert.from_event(e) for e in api_events]

        logger.info(f'Inserting {len(api_events)} new api events')
        await self.__alert_repository.insert_many(
            [e.to_dict() for e in api_events])

        # TODO: Send alerts

    async def get_api_event_history(
        self,
        start_timestamp: int,
        end_timestamp: int,
        include_body: bool = False
    ) -> List[Dict]:

        logger.info(
            f'Getting api event history from {start_timestamp} to {end_timestamp}')

        query = self.__repository.collection.find({
            'timestamp': {
                '$gte': start_timestamp,
                '$lte': end_timestamp
            }
        })

        records = await query.to_list(
            length=None)

        results = []
        for record in records:
            record.pop('_id')

            if not include_body:
                record.pop('response')
                record.pop('message')

            results.append(record)

        logger.info(f'Found {len(records)} event history records')

        return results
