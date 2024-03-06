import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import aiofiles
from clients.email_gateway_client import EmailGatewayClient
from clients.storage_client import StorageClient
from data.mongo_export_repository import MongoExportRepository
from domain.mongo import (MongoBackupConstants, MongoExportBlob,
                          MongoExportHistoryRecord, MongoExportPurgeResult,
                          MongoExportResult)
from domain.mongo_backup import MONGO_TOOLS_ARG, MONGO_TOOLS_CWD
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger

logger = get_logger(__name__)


class MongoBackupService:
    def __init__(
        self,
        export_repository: MongoExportRepository,
        storage_client: StorageClient,
        configuration: Configuration,
        email_client: EmailGatewayClient
    ):
        self._storage_client = storage_client
        self._email_gateway_client = email_client
        self._export_repository = export_repository

        self._connection_string = configuration.mongo.get(
            'connection_string')

    async def export_backup(
        self,
        purge_days: int
    ) -> MongoExportResult:

        ArgumentNullException.if_none(purge_days, 'purge_days')

        logger.info('Mongo backup export started')
        export_start = datetime.utcnow()

        # Run mongodump as subprocess
        stdout, stderr = await self.__run_backup_subprocess()
        export_end = datetime.utcnow()

        blob_name = self.__get_export_name()
        logger.info(f'Uploading to blob storage: {blob_name}')

        # Upload the export to blob storage
        upload_start = datetime.utcnow()

        blob_result = await self.__upload_export_blob(
            blob_name=blob_name)

        upload_end = datetime.utcnow()
        logger.info(f'Upload complete in: {upload_end - upload_start}')

        # Purge any expired exports
        purged = await self.__purge_expired_exports(
            days=int(purge_days))

        # Send email notification that process
        # is complete
        await self.__send_email_notification(
            blob_name=blob_name)

        await self.__write_history_record(
            blob_name=blob_name,
            elapsed=(export_end - export_start))

        return MongoExportResult(
            stdout=stdout,
            stderr=stderr,
            uploaded=blob_result,
            purged=purged)

    async def purge_exports(
        self,
        purge_days: int
    ) -> List[Dict]:

        ArgumentNullException.if_none(purge_days, 'purge_days')

        logger.info(f'Purge exports: {purge_days} day window')

        purged = await self.__purge_expired_exports(
            days=int(purge_days))

        return purged

    async def __run_backup_subprocess(
        self
    ) -> Tuple[str, str]:

        mongodump = f"./mongodump '{self._connection_string}' {MONGO_TOOLS_ARG}"
        logger.info(f'Running mongodump shell command: {mongodump}')

        process = await asyncio.create_subprocess_shell(
            mongodump,
            cwd=MONGO_TOOLS_CWD,
            stderr=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE)

        stdout, stderr = await process.communicate()

        if stdout:
            stdout = stdout.decode()
        if stderr:
            stderr = stderr.decode()

        logger.info(f'Mongodump stdout: {stdout}')
        logger.info(f'Mongodump stderr: {stderr}')

        return (stdout, stderr)

    def __get_export_name(
        self
    ) -> str:

        now = datetime.now().strftime(
            MongoBackupConstants.DateTimeFormat)

        return f'mongo__{now}'

    async def __purge_expired_exports(
        self,
        days: int
    ) -> List[Dict]:

        ArgumentNullException.if_none(days, 'days')

        # Existing backups
        storage_blobs = await self._storage_client.get_blobs(
            container_name=MongoBackupConstants.ContainerName)

        blobs = [MongoExportBlob(data=blob)
                 for blob in storage_blobs]

        purged = []
        purge_queue = []

        # Find blobs that exceed the purge window
        for blob in blobs:
            logger.info(f'Blob: {blob.blob_name}: Age: {blob.days_old}')

            if blob.days_old > days:
                logger.info(f'Age exceeds maximum threshold: {blob.blob_name}')

                # Add purged blob to results list
                purge_queue.append(blob)
                result = MongoExportPurgeResult(
                    blob_name=blob.blob_name,
                    created_date=blob.created_date,
                    days_old=blob.days_old)

                purged.append(result.to_dict())

        if any(purge_queue):
            # Get a list of distinct blob names
            # to purge
            blob_names = list(set([
                blob.blob_name
                for blob in purge_queue
            ]))

            logger.info(f'{len(blob_names)} blobs enqueued to purge')

            for purge_blob in blob_names:
                logger.info(f'Deleting blob: {purge_blob}')

                # Delete the blob
                await self._storage_client.delete_blob(
                    container_name=MongoBackupConstants.ContainerName,
                    blob_name=purge_blob)

        return purged

    async def __upload_export_blob(
        self,
        blob_name: str
    ) -> Dict:

        ArgumentNullException.if_none_or_whitespace(blob_name, 'blob_name')

        logger.info(f'Loading export: {MongoBackupConstants.ExportFilepath}')

        async with aiofiles.open(MongoBackupConstants.ExportFilepath, 'rb') as dump:
            blob_data = await dump.read()
            logger.info(f'Dump file loaded successfully')

            result = await self._storage_client.upload_blob(
                container_name=MongoBackupConstants.ContainerName,
                blob_name=blob_name,
                blob_data=blob_data)

            return result

    # async def __send_email_notification(
    #     self,
    #     blob_name: str,
    #     elapsed: timedelta
    # ) -> None:

    #     ArgumentNullException.if_none_or_whitespace(blob_name, 'blob_name')

    #     logger.info('Sending notification email')

    #     # await self.__email_client.send_email(
    #     #     subject='MongoDB Backup Service',
    #     #     recipient='dcl525@gmail.com',
    #     #     message=f'MongoDB backup completed successfully: {blob_name}')

    #     email_request, endpoint = self.__email_gateway_client.get_email_request(
    #         recipient=EMAIL_RECIPIENT,
    #         subject=EMAIL_SUBJECT,
    #         body=f'MongoDB backup completed successfully in {round(elapsed, 2)}s: {blob_name}')

    #     await self.__event_service.dispatch_email_event(
    #         endpoint=endpoint,
    #         message=email_request.to_dict())

    async def __send_email_notification(
        self,
        blob_name: str
    ) -> None:

        ArgumentNullException.if_none_or_whitespace(blob_name, 'blob_name')

        logger.info('Sending notification email')

        await self._email_gateway_client.send_email(
            subject='MongoDB Backup Service',
            recipient='dcl525@gmail.com',
            message=f'MongoDB backup completed successfully: {blob_name}')

    async def __write_history_record(
        self,
        blob_name: str,
        elapsed: timedelta,
        stdout: str,
        stderr: str
    ) -> None:

        ArgumentNullException.if_none_or_whitespace(blob_name, 'blob_name')

        record = MongoExportHistoryRecord(
            blob_name=blob_name,
            elapsed=elapsed,
            stderr=stderr,
            stdout=stdout)

        logger.info(f'Writing history record: {record.to_dict()}')

        await self._export_repository.insert(
            document=record.to_dict())
