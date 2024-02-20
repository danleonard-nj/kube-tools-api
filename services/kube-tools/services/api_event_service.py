import time
from typing import Dict, List

from data.api_event_repository import (ApiEventAlertRepository,
                                       ApiEventRepository)
from domain.api_events import ApiEventAlert
from framework.logger import get_logger
from framework.serialization import Serializable

DEFAULT_ALERT_LOOKBACK_HOURS = 1

logger = get_logger(__name__)


class ApiEventHistoryService:
    def __init__(
        self,
        repository: ApiEventRepository,
        alert_repostory: ApiEventAlertRepository
    ):
        self._repository = repository
        self._alert_repository = alert_repostory

    async def poll_event_alerts(
        self,
        hours_back: int | None = None,
    ):

        logger.info(f'Polling for api event alerts: {hours_back} hours back')
        hours_back = hours_back or DEFAULT_ALERT_LOOKBACK_HOURS

        error_event_entities = await self._repository.get_error_events()

        error_events = [ApiEventAlert.from_event(e)
                        for e in error_event_entities]

        event_ids = [e.event_id for e in error_events]

        cutoff_timestamp = int(time.time()) - (hours_back * 60 * 60)

        api_events = await self._repository.get_events_by_log_ids(
            cutoff_timestamp=cutoff_timestamp,
            log_ids=event_ids)

        if not any(api_events):
            logger.info('No new api events found')
            return []

        logger.info(f'Found {len(api_events)} new api events')

        api_events = [ApiEventAlert.from_event(e) for e in api_events]

        logger.info(f'Inserting {len(api_events)} new api events')
        await self._alert_repository.insert_many(
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

        records = await self._repository.get_events(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp
        )

        results = []
        for record in records:
            record.pop('_id')

            if not include_body:
                record.pop('response')
                record.pop('message')

            results.append(record)

        logger.info(f'Found {len(records)} event history records')

        return results
