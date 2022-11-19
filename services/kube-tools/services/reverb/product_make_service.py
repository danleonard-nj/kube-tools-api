from framework.logger import get_logger

from data.reverb_service_repositories import ProductMakeRepository
from domain.reverb.product import ReverbProductMake

logger = get_logger(__name__)


class ReverbProductMakeService:
    def __init__(
        self,
        repository: ProductMakeRepository
    ):
        self.__repository = repository

    async def get_product_make(
        self,
        product_make: str
    ) -> ReverbProductMake:
        logger.info(f'Get product make: {product_make}')

        entity = await self.__repository.get_product_make(
            product_make=product_make)

        if entity is not None:
            return ReverbProductMake.from_entity(
                data=entity)

    async def create_product_make(
        self,
        product_make: str
    ):
        logger.info(f'Creating product make: {product_make}')
        model = ReverbProductMake.create_product_make(
            product_make=product_make)

        await self.__repository.insert(
            document=model.to_dict())

        return model

    async def get_or_create_make(self, product_make):
        logger.info(f'Getting make: {product_make}')

        existing_make = await self.get_product_make(
            product_make=product_make)

        if existing_make is not None:
            logger.info(f'Record for make {product_make} found')
            return existing_make

        logger.info(f'Creating record for make: {product_make}')
        return await self.create_product_make(
            product_make=product_make)
