import uuid
from typing import Dict

from framework.clients.feature_client import FeatureClientAsync
from framework.logger import get_logger

from data.pfsense_log_repository import PfSenseLogRepository
from domain.features import Feature
from utilities.utils import DateTimeUtil

logger = get_logger(__name__)


class PfSenseLogService:
    def __init__(
        self,
        log_repository: PfSenseLogRepository,
        feature_client: FeatureClientAsync
    ):
        self.__log_repository = log_repository
        self.__feature_client = feature_client

    async def capture_log(
        self,
        log: Dict
    ):
        is_enabled = await self.__feature_client.is_enabled(
            feature_key=Feature.PfSenseLogIngestion)

        if not is_enabled:
            logger.info(f'PfSense log ingestion is disabled')
            return

        logger.info(f'Capturing pfSense log file')

        metadata = {
            'record_id': str(uuid.uuid4()),
            'captured': DateTimeUtil.timestamp()
        }

        record = metadata | log

        await self.__log_repository.insert(
            document=record)

        return record
