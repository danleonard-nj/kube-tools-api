from framework.logger import get_logger

from data.reverb_service_repositories import ProductRepository
from domain.reverb.listings import ReverbListing
from domain.reverb.product import ReverbProduct
from services.reverb.condition_service import ReverbProductConditionService
from services.reverb.listing_service import ReverbListingService
from services.reverb.product_make_service import ReverbProductMakeService
from services.reverb.transaction_comparison_service import \
    ReverbTransactionComparisonService

logger = get_logger(__name__)


class ReverbProductService:
    def __init__(
        self,
        repository: ProductRepository,
        product_make_service: ReverbProductMakeService,
        transaction_comparison_service: ReverbTransactionComparisonService,
        listing_service: ReverbListingService,
        condition_service: ReverbProductConditionService
    ):
        self.__repository = repository
        self.__product_make_service = product_make_service
        self.__transaction_comparison_service = transaction_comparison_service
        self.__listing_service = listing_service
        self.__condition_service = condition_service

    async def get_product_by_key(
        self,
        product_key: str
    ) -> ReverbProduct:

        entity = await self.__repository.get_product_by_key(
            product_key=product_key)

        if entity is not None:
            return ReverbProduct.from_entity(
                data=entity)

    async def get_product(
        self,
        product_id: str
    ):
        pass

    async def create_product(
        self,
        listing: ReverbListing
    ):

        make = await self.__product_make_service.get_product_make(
            product_make=listing.make)

        if make is None:
            logger.info(f'Creating product make: {listing.make}')

            make = await self.__product_make_service.create_product_make(
                product_make=listing.make)

        logger.info(f'Fetched product make ID: {make.product_make_id}')

        listing_detail = await self.__listing_service.get_listing_detail(
            listing_bk=listing.bk)

        product = ReverbProduct.from_listing(
            listing=listing,
            product_make_id=make.product_make_id)

        # Comaprison shopping page will give us the product 'slug' or
        # the product key that links the listings back to a single entity
        # which we can pull transaction history for
        if listing_detail.comparison_shopping is not None:
            comaprison_page = await self.__transaction_comparison_service.get_comparison_shopping_page(
                link=listing_detail.comparison_shopping)

            logger.info(
                f'Product: {product.product_id}: Normalized title: {comaprison_page.product_name}')

            # Use the product BK and normalized product title
            product.product_bk = comaprison_page.product_bk
            product.product_model = comaprison_page.product_name

            logger.info(f'Created product: {product.product_id}')

            await self.__repository.insert(
                document=product.to_dict())

            return product

        logger.info(f'Ignoring nonstandard product with no product key')
