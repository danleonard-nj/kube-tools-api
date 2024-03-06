from datetime import datetime
from typing import List, Union

import pandas as pd
import pytz
from clients.azure_gateway_client import AzureGatewayClient
from clients.email_gateway_client import EmailGatewayClient
from dateutil import parser
from domain.acr import format_result_row, format_row
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
from services.acr_service import AcrImage, AcrService
from services.event_service import EventService

logger = get_logger(__name__)


class AcrPurgeService:
    def __init__(
        self,
        configuration: Configuration,
        email_client: EmailGatewayClient,
        event_service: EventService,
        azure_gateway_client: AzureGatewayClient,
        acr_service: AcrService
    ):
        self._acr_service = acr_service
        self._email_client = email_client
        self._event_service = event_service
        self._azure_gateway_client = azure_gateway_client
        self._exclusions = configuration.acr_purge.get(
            'exclusions', [])

    async def purge_images(
        self,
        days_back: str | int,
        top_count: str | int
    ):
        ArgumentNullException.if_none_or_whitespace(days_back, 'days_back')
        ArgumentNullException.if_none_or_whitespace(top_count, 'top_count')

        logger.info(f'Days back: {days_back}')
        logger.info(f'Keep top image count by repo: {top_count}')

        # Parse the days back and top count
        days_back = int(days_back)
        top_count = int(top_count)

        processed_images = []
        repos = await self._acr_service.get_acr_repo_names()

        # Get a list of all the active images running
        # in the cluster to be excluded from the purge
        active_images = await self._azure_gateway_client.get_pod_images()

        active_image_pods = active_images.get(
            'pods', [])

        active_df = pd.DataFrame([
            format_row(image)
            for image in active_image_pods
        ])

        for repo in repos:
            logger.info(f'Processing repo: {repo}')

            # Verify the repo is not excluded by
            # evaluating the exclusion rules defined
            # in the service configuration
            if self._is_excluded(
                    repository_name=repo):
                continue

            purged_images = await self.purge_repo(
                active_images=active_df,
                repo_name=repo,
                days_back=days_back,
                top_count=top_count)

            logger.info(f'Purge images for repo: {repo}: {len(purged_images)}')

            processed_images.extend([
                format_result_row(image, repo)
                for image in purged_images
            ])

        if any(processed_images):
            email_request, endpoint = self._email_client.get_datatable_email_request(
                recipient='dcl525@gmail.com',
                subject='ACR Purge',
                data=processed_images)

            await self._event_service.dispatch_email_event(
                endpoint=endpoint,
                message=email_request.to_dict())

        return processed_images

    async def purge_repo(
        self,
        repo_name: str,
        active_images: pd.DataFrame,
        days_back: Union[str, int] = 3,
        top_count: Union[str, int] = 3,
    ) -> List[AcrImage]:

        ArgumentNullException.if_none_or_whitespace(repo_name, 'repo_name')
        ArgumentNullException.if_none(active_images, 'active_images')
        ArgumentNullException.if_none_or_whitespace(days_back, 'days_back')

        logger.info(f'Get images for repo: {repo_name}')

        images = await self._acr_service.get_manifests(
            repo_name=repo_name)

        now = datetime.utcnow().astimezone(tz=pytz.UTC)
        days_back = int(days_back)
        top_count = int(top_count)

        processing_data = [
            image.to_dict()
            for image in images
        ]

        df = pd.DataFrame(processing_data)

        for index in df.index:
            created_date = df.loc[index, 'created_date']
            tag = df.loc[index, 'tag']

            created_date = parser.parse(created_date)
            days_old = (now - created_date).days

            df.loc[index, 'days_old'] = days_old
            df.loc[index, 'exceeds_age'] = days_old > days_back

            image_name = f'{repo_name}:{tag}'
            image_name = f'azureks.azurecr.io/{image_name}'
            df.loc[index, 'image_name'] = image_name

        df = df.sort_values(by=['days_old'])
        df = df.merge(
            active_images,
            how='left',
            left_on='image_name',
            right_on='active_image')

        df = df[df['active_image'].isna()]
        df = df[top_count:]
        df = df[df['exceeds_age'] == True]

        processed_images = df.to_dict(orient='records')
        processed_images = [
            AcrImage.from_dict(data=image)
            for image in processed_images
        ]

        logger.info(f'Repo: {repo_name}: Purge count: {len(processed_images)}')

        for image in processed_images:
            await self._acr_service.purge_image(
                repo_name=repo_name,
                manifest_id=image.id)

        return processed_images

    def _is_excluded(
        self,
        repository_name: str
    ):
        for exclusion in self._exclusions:
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
