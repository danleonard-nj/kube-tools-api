from typing import Dict, List, Union

from azure.storage.blob import BlobProperties
from azure.storage.blob.aio import BlobServiceClient, ContainerClient
from framework.configuration.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger

logger = get_logger(__name__)


class StorageClient:
    def __init__(
        self,
        configuration: Configuration
    ):
        self.__connection_string = configuration.storage.get(
            'connection_string')

    def __get_blob_service_client(
        self
    ) -> BlobServiceClient:

        return BlobServiceClient.from_connection_string(
            conn_str=self.__connection_string)

    async def upload_blob(
        self,
        container_name: str,
        blob_name: str,
        blob_data: bytes
    ) -> Dict:

        ArgumentNullException.if_none_or_whitespace(
            container_name, 'container_name')
        ArgumentNullException.if_none_or_whitespace(
            blob_name, 'blob_name')
        ArgumentNullException.if_none(
            blob_data, 'blob_data')

        logger.info(f'Uploading blob: {container_name}: {blob_name}')

        async with self.__get_blob_service_client() as client:
            logger.info(
                f'Getting blob container client for container: {container_name}')
            container_client: ContainerClient = client.get_container_client(
                container=container_name)

            logger.info(f'Getting blob client for blob: {blob_name}')
            blob_client = container_client.get_blob_client(blob_name)

            logger.info('Uploading blob data to storage')
            await blob_client.upload_blob(blob_data)
            logger.info('Blob uploaded successfully')

    async def get_blobs(
        self,
        container_name: str
    ) -> List[Dict]:

        ArgumentNullException.if_none_or_whitespace(
            container_name, 'container_name')

        async with self.__get_blob_service_client() as client:
            logger.info(
                f'Getting blob container client for container: {container_name}')
            container_client: ContainerClient = client.get_container_client(
                container=container_name)

            blobs = container_client.list_blobs()
            results: List[BlobProperties] = []
            async for blob in blobs:
                results.append(blob.__dict__)

            return results

    async def download_blob(
        self,
        container_name: str,
        blob_name: str
    ) -> Union[bytes, None]:

        ArgumentNullException.if_none_or_whitespace(
            container_name, 'container_name')
        ArgumentNullException.if_none_or_whitespace(
            blob_name, 'blob_name')

        logger.info(f'Downloading blob: {container_name}: {blob_name}')

        async with self.__get_blob_service_client() as client:
            logger.info(
                f'Getting blob container client for container: {container_name}')
            container_client: ContainerClient = client.get_container_client(
                container=container_name)

            logger.info(f'Getting blob client for blob: {blob_name}')
            blob_client = container_client.get_blob_client(blob_name)

            logger.info(f'Downloading blobl data from storage')
            blob = await blob_client.download_blob()

            logger.info(f'Reading blob download stream to file')
            data = await blob.readall()

            logger.info(f'Blob downloaded successfully')
            return data

    async def delete_blob(
        self,
        container_name: str,
        blob_name: str
    ) -> Union[bytes, None]:

        ArgumentNullException.if_none_or_whitespace(
            container_name, 'container_name')
        ArgumentNullException.if_none_or_whitespace(
            blob_name, 'blob_name')

        logger.info(f'Deleting blob: {container_name}: {blob_name}')

        async with self.__get_blob_service_client() as client:
            logger.info(
                f'Getting blob container client for container: {container_name}')
            container_client: ContainerClient = client.get_container_client(
                container=container_name)

            logger.info(f'Getting blob client for blob: {blob_name}')
            blob_client = container_client.get_blob_client(blob_name)

            blob_exists = await blob_client.exists()
            logger.info(f'Blob: {blob_name}: Blob exists: {blob_exists}')

            if not blob_exists:
                logger.info(f'Blob does not exist: {blob_name}')
                return

            logger.info(f'Deleting blob: {blob_name}')
            await blob_client.delete_blob(delete_snapshots='include')

            logger.info(f'Blob deleted successfully')
