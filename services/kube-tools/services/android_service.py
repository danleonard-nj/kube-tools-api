from framework.logger import get_logger
from data.android_repository import AndroidNetworkDiagnosticsRepository

logger = get_logger(__name__)


class AndroidService:
    def __init__(
        self,
        repository: AndroidNetworkDiagnosticsRepository
    ):
        self._repository = repository

    async def capture_network_diagnostics(
        self,
        network_diagnostics: dict
    ):
        """
        Capture network diagnostics data.

        :param network_diagnostics: Dictionary or list of dictionaries containing network diagnostics data.
        """

        logger.info(f"Capturing network diagnostics: {network_diagnostics}")

        # Support both single dict and list of dicts
        if isinstance(network_diagnostics, list):
            await self._repository.collection.insert_many(network_diagnostics)
        else:
            await self._repository.collection.insert_one(network_diagnostics)

        return network_diagnostics
