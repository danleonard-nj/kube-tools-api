import time
from typing import Dict, List

from data.api_event_repository import ApiEventRepository
from domain.api_events import ApiEventAlert
from framework.logger import get_logger

DEFAULT_ALERT_LOOKBACK_HOURS = 1

logger = get_logger(__name__)


class ApiEventHistoryService:
    def __init__(
        self,
        repository: ApiEventRepository,
    ):
        self._repository = repository

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

    async def purge_events_older_than(self, days: int) -> int:
        """Purge api event records older than `days` days.

        Returns the number of deleted documents.
        """
        logger.info(f'Purging api events older than {days} days')

        # convert days to seconds and compute cutoff unix timestamp
        cutoff_timestamp = int(time.time()) - (days * 24 * 60 * 60)

        # many repositories expose `collection` (see other repos) so call delete_many
        result = await self._repository.collection.delete_many({
            'timestamp': {'$lt': cutoff_timestamp}
        })

        deleted = int(getattr(result, 'deleted_count', 0))
        logger.info(f'Purged {deleted} api events')
        return deleted
