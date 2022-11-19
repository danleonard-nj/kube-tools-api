from typing import List

import pandas as pd
from clients.azure_gateway_client import AzureGatewayClient
from clients.email_gateway_client import EmailGatewayClient
from domain.acr import AcrServiceCacheKey, Image, ManifestInfo, RepositoryInfo
from domain.email import EmailGatewayConstants
from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from framework.logger.providers import get_logger
from framework.concurrency import TaskCollection

logger = get_logger(__name__)


class AcrService:
    def __init__(
        self,
        azure_gateway_client: AzureGatewayClient,
        cache_client: CacheClientAsync,
        email_gateway_client: EmailGatewayClient,
        configuration: Configuration
    ):
        self.__azure_gateway_client = azure_gateway_client
        self.__cache_client: CacheClientAsync = cache_client
        self.__email_gateway_client = email_gateway_client

        self.__days_back = configuration.acr_purge.get(
            'days_back', 14)
        self.__keep_top_image_count = configuration.acr_purge.get(
            'keep_top_image_count', 3)
        self.__exclusions = configuration.acr_purge.get(
            'exclusions', [])

    def __to_manifest_info(
        self,
        manifest,
        repository
    ):
        if (manifest.get('tags') is not None
                and len(manifest.get('tags')) > 0):

            return ManifestInfo(
                manifest=manifest,
                repository_name=repository)

    async def __get_repository_manifests(
        self,
        repository: str
    ) -> List[RepositoryInfo]:

        result = await self.__azure_gateway_client.acr_get_manifests(
            repository_name=repository)

        manifests = result.get('manifests', [])

        manifest_info = []
        for manifest in manifests:

            digest_id = manifest.get('digest')
            logger.info(f'Manifest {digest_id}: Parsing ACR manifest')

            manifest_info.append(
                self.__to_manifest_info(
                    manifest=manifest,
                    repository=repository))

        repo_manifests = [
            item for item in manifest_info
            if item is not None
        ]

        return RepositoryInfo(
            repository_name=repository,
            manifests=repo_manifests)

    async def __get_repository_info(
        self
    ) -> List[RepositoryInfo]:
        '''
        Get all manifests for all repositories
        '''

        logger.info('Fetching manifests from gateway client')

        # Get all repositories
        result = await self.__azure_gateway_client.acr_get_repositories()
        repositories = result.get('repositories')

        # Fetch manifests by repository and append to list
        fetch = TaskCollection()
        for repository in repositories:
            logger.info(f'{repository}: Fetching repository manifests')

            # Fetch the manifests for a single repository
            fetch.add_task(self.__get_repository_manifests(
                repository=repository))

        return await fetch.run()

    def __get_k8s_image_repo(self, image_name):
        if 'azureks.azurecr.io' in image_name:
            segments = image_name.split('azureks.azurecr.io/')
            if any(segments):
                image_segment = segments[1]
                tag_segments = image_segment.split(':')
                if any(tag_segments):
                    return tag_segments[0]
        return image_name

    async def __get_k8s_images(
        self
    ) -> List:
        '''
        Get all active ACR images in the K8S
        cluster
        '''
        logger.info('K8S Images: Fetching K8S images from gateway client')
        # Get a list of all pods from all namespaces
        result = await self.__azure_gateway_client.get_pod_images()

        # Loop through all pods and get the image name
        pods = result.get('pods')
        images = [{
            'image': pod,
            'repository': self.__get_k8s_image_repo(pod)
        } for pod in pods if 'azureks' in pod]

        return images

    async def __send_email(
        self,
        purged: list[ManifestInfo]
    ) -> None:
        logger.info(f'Sending email result')

        image_info = [
            x.get_image_info()
            for x in purged
        ]

        data = [{
            'Repository': image.repository,
            'Image': image.image_name,
            'Tag': image.tag,
            'DaysOld': image.days_old,
            'Size': image.size
        } for image in image_info]

        await self.__email_gateway_client.send_datatable_email(
            recipient=EmailGatewayConstants.Me,
            subject='ACR Purge',
            data=data)

    def __get_k8s_image_counts_by_repository(self, k8s_images):
        df = pd.DataFrame(k8s_images).groupby(
            'repository').count()

        df = df.rename(columns={
            'image': 'count'
        })

        return df.reset_index().to_dict(
            orient='records')

    async def __purge_images(self, purge: List[ManifestInfo]):
        logger.info('Purging queued images')

        purge_tasks = TaskCollection()
        for image in purge:
            logger.info(
                f'Image: {image.full_name}: Deleting image from ACR')

            # Delete request to gateway
            purge_tasks.add_tasks(
                self.__azure_gateway_client.acr_delete_manifest(
                    repository_name=image.image_name,
                    manifest_id=image.id),
                self.__cache_client.delete_key(
                    key=AcrServiceCacheKey.ManifestInfo))

        await purge_tasks.run()
        await self.__send_email(
            purged=purge)

    def __is_excluded(self, repository):
        for exclusion in self.__exclusions:
            logger.info(f"Rule: [{exclusion}]: evaluating rule")
            try:
                if eval(exclusion) is True:
                    logger.info(f'{exclusion}: True')
                    return True
            except Exception as ex:
                logger.info(
                    f"Rule: [{exclusion}]: failed to evaluate rule: {str(ex)}")
                pass

        logger.info(f"Rule: [{exclusion}]: False")
        return False

    async def purge_acr(
        self,
    ):
        '''
        Purge ACR images older than the specified day threshold

        Args:
            days (int, optional): purge window days. Defaults to 2.

        Returns:
            dict: purge results
        '''

        # Get all image names from all active K8S pods
        k8s_images = await self.__get_k8s_images()
        logger.info(f'{len(k8s_images)} pod images fetched')

        k8s_image_counts = self.__get_k8s_image_counts_by_repository(
            k8s_images=k8s_images)

        # Get manifests from ACR
        repositories = await self.__get_repository_info()
        logger.info(f'{len(repositories)} repos fetched')

        purge = []
        for repository in repositories:
            logger.info(f'Repository: {repository.repository_name}')

            if self.__is_excluded(repository=repository):
                logger.info(
                    f'Excluding repository: {repository.repository_name}')
                continue

            repo_purge = repository.get_purge_images(
                k8s_images=k8s_images,
                k8s_image_counts=k8s_image_counts,
                threshold_days=self.__days_back,
                keep_top_image_count=self.__keep_top_image_count)

            if any(repo_purge):
                purge.extend(repo_purge)

            logger.info(f'Purge: {len(repo_purge)}')

        logger.info(f'Images to purge: {len(purge)}')
        if len(purge) > 0:
            await self.__purge_images(
                purge=purge)

        return {
            'results': [x.full_name for x in purge],
            'total_size': sum([float(x.size or 0) for x in purge])
        }
