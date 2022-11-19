import asyncio
from datetime import datetime
from typing import Dict, List

import aiofiles
from clients.email_gateway_client import EmailGatewayClient
from clients.storage_client import StorageClient
from domain.mongo import MongoBackupConstants
from framework.configuration import Configuration
from framework.logger import get_logger
from framework.concurrency import TaskCollection

logger = get_logger(__name__)


class MongoBackupService:
    def __init__(
        self,
        storage_client: StorageClient,
        configuration: Configuration,
        email_client: EmailGatewayClient
    ):
        self.__storage_client = storage_client
        self.__configuraiton = configuration
        self.__email_client = email_client

    async def export_backup(
        self,
        purge_days: int
    ) -> Dict:
        logger.info('Mongo backup export started')

        connection_string = self.__configuraiton.mongo.get(
            'connection_string')

        process = await asyncio.create_subprocess_shell(
            f"./mongodump '{connection_string}' --archive=dump.gz --gzip",
            cwd='/app/utilities/mongotools/bin',
            stderr=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE)

        stdout, stderr = await process.communicate()

        if stdout:
            stdout = stdout.decode()
        if stderr:
            stderr = stderr.decode()

        logger.info(f'Output: {stdout}')
        logger.info(f'Errors: {stderr}')

        logger.info(f'Uploading to blob storage')

        blob_name = self.__get_dump_name()
        blob_result = await self.__upload_dump(
            blob_name=blob_name)

        logger.info(f'Running purge routine')
        purged = await self.__purge_dumps(
            days=int(purge_days))

        logger.info('Sending notification email')
        await self.__email_client.send_email(
            subject='MongoDB Backup Service',
            recipient='dcl525@gmail.com',
            message=f'MongoDB backup completed successfully: {blob_name}')

        return {
            'stdout': stdout,
            'stderr': stderr,
            'uploaded': blob_result,
            'purged': purged
        }

    def __get_dump_name(
        self
    ) -> str:
        '''
        Get the formatted name of the export

        Returns:
            str: _description_
        '''

        iso = datetime.now().strftime(
            MongoBackupConstants.DateTimeFormat)

        return f'mongo__{iso}'

    async def __purge_dumps(
        self,
        days: int
    ) -> List[Dict]:
        blobs = await self.__storage_client.get_blobs(
            container_name=MongoBackupConstants.ContainerName)

        tasks = TaskCollection()
        purged = []

        # Find blobs that exceed the purge window
        for blob in blobs:
            blob_name = blob.get('name')
            blob_created_date = blob.get('creation_time')

            # Get the age of the backup
            current_timestamp = int(datetime.now().timestamp())
            created_timestamp = int(blob_created_date.timestamp())

            days_old = self.__get_days_old(
                now=current_timestamp,
                created=created_timestamp)

            logger.info(f'Blob: {blob_name}: Age: {days_old}')

            if days_old > days:
                logger.info(f'Purging blob: {blob_name}')
                tasks.add_task(
                    self.__storage_client.delete_blob(
                        container_name=MongoBackupConstants.ContainerName,
                        blob_name=blob_name))

                # Add purged blob to results list
                purged.append({
                    'blob': blob_name,
                    'created': blob_created_date,
                    'age': days_old
                })

            if any(tasks._tasks):
                logger.info(f'Running purge tasks')
                await tasks.run()

        return purged

    def __get_days_old(
        self,
        now: int,
        created: int
    ) -> float:
        logger.info(f'Now: {now} Created: {created}')

        delta = now - created
        if delta != 0:
            minutes = delta / 60
            hours = minutes / 60
            days = hours / 24

            logger.info(f'Minutes: {minutes}: Hours: {hours}: Days: {days}')

            return days
        return 0

    async def __upload_dump(
        self,
        blob_name: str
    ) -> dict:
        async with aiofiles.open('/app/utilities/mongotools/bin/dump.gz', 'rb') as dump:
            logger.info(f'Dump file loaded successfully')

            blob_data = await dump.read()
            result = await self.__storage_client.upload_blob(
                container_name='mongo-dumps',
                blob_name=blob_name,
                blob_data=blob_data)

            return result
