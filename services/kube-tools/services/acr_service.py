from clients.azure_gateway_client import AzureGatewayClient
from domain.acr import AcrImage
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger

logger = get_logger(__name__)


class AcrService:
    def __init__(
        self,
        azure_gateway_client: AzureGatewayClient
    ):
        self._azure_gateway_client = azure_gateway_client

    async def purge_image(
        self,
        repo_name: str,
        manifest_id: str
    ) -> None:

        ArgumentNullException.if_none_or_whitespace(repo_name, 'repo_name')
        ArgumentNullException.if_none_or_whitespace(manifest_id, 'manifest_id')

        logger.info(f'Purging image: {repo_name}: {manifest_id}')

        response = await self._azure_gateway_client.acr_delete_manifest(
            repository_name=repo_name,
            manifest_id=manifest_id)

        return response

    async def get_manifests(
        self,
        repo_name: str
    ):
        ArgumentNullException.if_none_or_whitespace(repo_name, 'repo_name')

        logger.info(f'Get images for repo: {repo_name}')

        images = await self._azure_gateway_client.acr_get_manifests(
            repository_name=repo_name)

        manifests = images.get('manifests')

        logger.info(f'Fetched {len(manifests)} manifests for repo: {repo_name}')

        return [
            AcrImage.from_manifest(data=manifest)
            for manifest in manifests
        ]

    async def get_acr_repo_names(
        self
    ):
        repos = await self._azure_gateway_client.acr_get_repositories()

        logger.info(f'Repos: {repos}')

        return repos.get('repositories', [])
