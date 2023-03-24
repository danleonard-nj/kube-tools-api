from typing import Dict, List, Union

from azure.storage.blob import BlobProperties
from azure.storage.blob.aio import (BlobClient, BlobServiceClient,
                                    ContainerClient)
from framework.configuration.configuration import Configuration
from framework.logger.providers import get_logger
from httpx import AsyncClient

logger = get_logger(__name__)


class StorageClient:
    def __init__(
        self,
        configuration: Configuration
    ):
        self.connection_string = configuration.storage.get(
            'connection_string')

    def __get_blob_service_client(self):
        return BlobServiceClient.from_connection_string(
            conn_str=self.connection_string)

    async def upload_blob(
        self,
        container_name: str,
        blob_name: str,
        blob_data: bytes
    ) -> dict:
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

    async def download_blob(self, container_name: str, blob_name: str) -> Union[bytes, None]:
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

    async def delete_blob(self, container_name: str, blob_name: str) -> Union[bytes, None]:
        logger.info(f'Deleting blob: {container_name}: {blob_name}')

        async with self.__get_blob_service_client() as client:
            logger.info(
                f'Getting blob container client for container: {container_name}')
            container_client: ContainerClient = client.get_container_client(
                container=container_name)

            logger.info(f'Getting blob client for blob: {blob_name}')
            blob_client = container_client.get_blob_client(blob_name)

            logger.info(f'Downloading blobl data from storage')
            await blob_client.delete_blob(delete_snapshots='include')

            logger.info(f'Blob deleted successfully')
