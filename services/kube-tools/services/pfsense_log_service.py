

from typing import Dict
import uuid
from data.pfsense_log_repository import PfSenseLogRepository
from framework.logger import get_logger

from utilities.utils import DateTimeUtil

logger = get_logger(__name__)


class PfSenseLogService:
    def __init__(
        self,
        log_repository: PfSenseLogRepository
    ):
        self.__log_repository = log_repository

    async def capture_log(
        self,
        log: Dict
    ):
        logger.info(f'Capturing pfSense log file')

        metadata = {
            'record_id': str(uuid.uuid4()),
            'captured': DateTimeUtil.timestamp()
        }

        record = metadata | log

        await self.__log_repository.insert(
            document=record)

        return record
