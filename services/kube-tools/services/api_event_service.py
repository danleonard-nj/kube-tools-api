from typing import Dict, List

from framework.logger import get_logger

from data.api_event_repository import ApiEventRepository

logger = get_logger(__name__)


class ApiEventHistoryService:
    def __init__(
        self,
        repository: ApiEventRepository
    ):
        self.__repository = repository

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
