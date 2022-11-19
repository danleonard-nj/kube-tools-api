from datetime import datetime, timedelta
from typing import List

from framework.logger import get_logger

from clients.reverb_client import ReverbClient
from data.reverb_service_repositories import ProcessorListingRepository
from domain.reverb.listings import ReverbListing, ReverbListingDetail
from domain.reverb.product import ReverbProduct
from services.reverb.condition_service import ReverbProductConditionService
from domain.reverb.processor import ProcessorListing

logger = get_logger(__name__)


class ReverbListingService:
    def __init__(
        self,
        reverb_client: ReverbClient,
        processor_listing_repository: ProcessorListingRepository,
        condition_service: ReverbProductConditionService
    ):
        self.__reverb_client = reverb_client
        self.__processor_listing_repository = processor_listing_repository
        self.__condition_service = condition_service

    async def get_condition(
        self,
        listing: ReverbListing
    ):
        condition = await self.__condition_service.get_condition_by_key(
            condition_bk=listing.condition_bk)

        if condition is not None:
            return condition

        created_condition = await self.__condition_service.insert_condition(
            condition_name=listing.condition_name,
            condition_bk=listing.condition_bk)

        return created_condition

    async def create_processor_listing(
        self,
        listing: ReverbListing,
        product: ReverbProduct
    ) -> ProcessorListing:

        condition = await self.get_condition(
            listing=listing)

        processor_listing = ProcessorListing.from_listing(
            listing=listing,
            product=product,
            condition_id=condition.condition_id)

        await self.__processor_listing_repository.insert(
            processor_listing.to_dict())

        return processor_listing

    async def get_processor_listings(
        self,
        lookback_hours
    ):
        end = datetime.utcnow()
        start = datetime.utcnow() - timedelta(hours=lookback_hours)

        entities = await self.__processor_listing_repository.get_listings_by_date_range(
            start_date=start,
            end_date=end)

        if any(entities):
            return [ProcessorListing.from_entity(
                data=entity
            ) for entity in entities]

        return list()

    async def update_processor_listing(
        self,
        listing: ProcessorListing
    ):
        await self.__processor_listing_repository.replace(
            selector=listing.get_selector(),
            document=listing.to_dict())

    async def get_processor_listing(
        self,
        listing_bk
    ):
        entity = await self.__processor_listing_repository.get({
            'listing_bk': listing_bk
        })

        if entity is not None:
            processor_listing = ProcessorListing.from_entity(
                data=entity)

            return processor_listing

    async def get_listings(
        self,
        product_type: str,
        limit=10,
    ) -> List[ReverbListing]:

        logger.info(f'Fetching listings')
        response = await self.__reverb_client.get_listings(
            page=1,
            items_per_page=limit,
            product_type=product_type)

        response_listings = response.get(
            'listings', list())

        logger.info(f'{len(response_listings)} listings fetched')
        return [ReverbListing(data=listing)
                for listing in response_listings]

    async def get_listing_detail(
        self,
        listing_bk
    ) -> ReverbListingDetail:
        listing_detail = await self.__reverb_client.get_listing_detail(
            listing_bk=listing_bk)

        return ReverbListingDetail.from_response(
            data=listing_detail)
