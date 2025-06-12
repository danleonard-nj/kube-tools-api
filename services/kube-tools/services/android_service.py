
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

        :param network_diagnostics: Dictionary containing network diagnostics data.
        """

        logger.info(f"Capturing network diagnostics: {network_diagnostics}")

        await self._repository.insert(network_diagnostics)

        return network_diagnostics
