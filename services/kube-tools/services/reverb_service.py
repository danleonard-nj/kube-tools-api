import asyncio
from datetime import datetime, timedelta

from framework.logger import get_logger
from framework.configuration import Configuration
from domain.reverb.processor import ListingProcessStatus, ListingProcessStatusType, ProcessorListing
from domain.reverb.product import ReverbProduct
from services.reverb.listing_service import ReverbListingService
from services.reverb.product_service import ReverbProductService
from services.reverb.transaction_comparison_service import \
    ReverbTransactionComparisonService
from framework.validators.nulls import none_or_whitespace

logger = get_logger(__name__)


def where(items, func):
    results = []
    for item in items:
        if func(item) is True:
            results.append(item)
    return results

# Events to fetch product transactions?


class ReverbListingProcessor:
    def __init__(
        self,
        configuration: Configuration,
        listing_service: ReverbListingService,
        transaction_comparison_service: ReverbTransactionComparisonService,
        product_service: ReverbProductService
    ):
        self.__listing_service = listing_service
        self.__transaction_comparison_service = transaction_comparison_service
        self.__product_service = product_service

        self.__lookback_hours = configuration.reverb.get(
            'lookback_hours', 24)

    def verify_listing(self, listing: ProcessorListing):

        # Missing product ID
        if none_or_whitespace(listing.product_id):
            return ListingProcessStatus(
                code=ListingProcessStatusType.Error,
                message='No product mapped to listing')

        # Missing condition
        if none_or_whitespace(listing.condition_id):
            return ListingProcessStatus(
                code=ListingProcessStatusType.Error,
                message='No condition mapped to listing')

        # Missing listing BK
        if none_or_whitespace(listing.listing_bk):
            return ListingProcessStatus(
                code=ListingProcessStatusType.Error,
                message='No listing BK is defined')

        # Missing offer URL
        if none_or_whitespace(listing.offer_url):
            return ListingProcessStatus(
                code=ListingProcessStatusType.Error,
                message='No offer URL is defined')

        # Missing listing price
        if none_or_whitespace(listing.price):
            return ListingProcessStatus(
                code=ListingProcessStatusType.Error,
                message='No listing price is defined')

        # Missing listing total price
        if none_or_whitespace(listing.total):
            return ListingProcessStatus(
                code=ListingProcessStatusType.Error,
                message='No total price is defined')

        return ListingProcessStatus(
            code=ListingProcessStatusType.ReadyToProcess,
            message='Listing is ready to process')

    def handle_no_comaprison_transactions(
        self,
        listing: ProcessorListing
    ):
        listing.update_status(
            status=ListingProcessStatus(
                code=ListingProcessStatusType.NoComparisonTransactions,
                message='No stored transaction history for product'))

    async def handle_no_status(
        self,
        listing: ProcessorListing
    ):
        logger.info(
            f'Listing: {listing.listing_bk}: Evaluating initial status')

        listing.update_status(
            status=self.verify_listing(
                listing=listing))
        logger.info(
            f'Listing: {listing.listing_bk}: Status code: {listing.status_code}')

    async def handle_ready_to_process(
        self,
        listing: ProcessorListing
    ):
        transactions = await self.__transaction_comparison_service.get_transactions_by_product_condition(
            product_id=listing.product_id,
            condition_id=listing.condition_id)

        logger.info(
            f'Listing: {listing.listing_bk}: Condition: {listing.condition_id}')
        logger.info(
            f'Listing: {listing.listing_bk}: Comparison records: {len(transactions)}')

        # No comparison transactions for product status
        if not any(transactions):
            logger.info(
                f'Listing: {listing.listing_bk}: Product: {listing.product_id}: No comparison records')

            # product = await self.__product_service.get_product_by_key(
            #     product_key=)

            logger.info(f'Listing: {listing.listing_bk}: ')

            self.handle_no_comaprison_transactions(
                listing=listing)

        else:
            # If there are transactions to compare, set status
            # to ready to compare
            logger.info(
                f'Listing: {listing.listing_bk}: Product: {listing.product_id}: Ready to process transactions')

            listing.update_status(
                status=ListingProcessStatus(
                    code=ListingProcessStatusType.ReadyToCompare,
                    message='Ready to compare transactions'))

    async def process_listing(self, listing: ProcessorListing):
        # No status code is set
        if listing.status_code is None:
            await self.handle_no_status(
                listing=listing)

        # Ready to process status listings
        if listing.status_code == ListingProcessStatusType.ReadyToProcess:
            await self.handle_ready_to_process(
                listing=listing)

        if listing.status_code == ListingProcessStatusType.ReadyToCompare:
            # TODO: Compare listing with transactions
            logger.info(f'Ready to compare transactions!')

        if listing.status_code == ListingProcessStatusType.NoComparisonTransactions:
            # TODO: Fetch updated transactions
            logger.info(f'Recheck for transaction history if window exceeded')

        await self.__listing_service.update_processor_listing(
            listing=listing)

    async def process(self):
        listings = await self.__listing_service.get_processor_listings(
            lookback_hours=self.__lookback_hours)

        for listing in listings:

            await self.process_listing(
                listing=listing)

        return listings


class ReverbListingSyncService:
    def __init__(
        self,
        product_service: ReverbProductService,
        listing_service: ReverbListingService,
        transaction_comparison_service: ReverbTransactionComparisonService,
        configuration: Configuration
    ):
        self.__product_service = product_service
        self.__listing_service = listing_service
        self.__transaction_comparison_service = transaction_comparison_service
        self.__configuration = configuration

        self.__sync_interval = configuration.reverb.get('sync_interval')
        self.__delay = 1

    async def sync_product(self, listing):
        product_key = listing.get_product_key()
        logger.info(f'Product key: {product_key}')

        product = await self.__product_service.get_product_by_key(
            product_key=product_key)

        if product is not None:
            return (product, False)

        logger.info(f'No product exists with key {product_key}')
        product = await self.__product_service.create_product(
            listing=listing)

        return (product, True)

    async def sync_transactions(
        self,
        product: ReverbProduct,
        force_sync=False
    ):
        if product.product_bk is not None:
            if force_sync or product.get_hours_since_last_sync() >= self.__sync_interval:

                logger.info(
                    f'Product BK: {product.product_bk}: Sync transactions')
                await self.__transaction_comparison_service.sync_transactions(
                    product=product)

    async def get_listings(self):
        logger.info(f'Fetching listings')
        listings = await self.__listing_service.get_listings(
            product_type='effects-and-pedals',
            limit=25)

        processor_listings = []

        # Process listings
        for listing in listings:
            if not listing.local_shipping:
                logger.info(f'Listing BK: {listing.bk}: Non-local listing')
                continue

            processor_listing = await self.__listing_service.get_processor_listing(
                listing_bk=listing.bk)

            if processor_listing is not None:
                processor_listings.append(processor_listing)
                logger.info(
                    f'Listing BK: {listing.bk}: Processor listing exists')
                continue

            await asyncio.sleep(self.__delay)
            logger.info(f'Processing listing: {listing.bk}')

            product, force_sync = await self.sync_product(
                listing=listing)

            if product is None:
                continue

            await self.sync_transactions(
                product=product,
                force_sync=force_sync)

            processor_listing = await self.__listing_service.create_processor_listing(
                listing=listing,
                product=product)

            processor_listings.append(processor_listing)

        return processor_listings
