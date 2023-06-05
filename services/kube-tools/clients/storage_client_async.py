from framework.configuration.configuration import Configuration


class StorageClientAsync:
    def __init__(
        self,
        configuration: Configuration
    ):
        self.__connection_string = configuration.storage.get(
            'connection_string')

    async def get_blob(
        self,
        container_name: str,
        blob_name: str
    ) -> bytes:
        pass

    async def upload_blob(
        self,
        container_name: str,
        blob_name: str,
        blob: bytes
    ):
        pass

    async def delete_blob(
        self,
        container_name: str,
        blob_name: str
    ):
        pass

    async def list_blobs(
        self,
        container_name: str
    ) -> list:
        pass
