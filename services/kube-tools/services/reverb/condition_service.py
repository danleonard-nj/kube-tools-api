from framework.logger import get_logger

from data.reverb_service_repositories import ProductConditionRepository
from domain.reverb.product import ReverbProductCondition

logger = get_logger(__name__)


class ReverbProductConditionService:
    def __init__(
        self,
        repository: ProductConditionRepository
    ):
        self.__repository = repository

    async def get_condition_by_name(self, condition_name):
        entity = await self.__repository.get({
            'condition_name': condition_name
        })

        if entity is not None:
            return ReverbProductCondition.from_entity(
                data=entity)

    async def get_condition_by_key(self, condition_bk):
        entity = await self.__repository.get({
            'condition_bk': condition_bk
        })

        if entity is not None:
            return ReverbProductCondition.from_entity(
                data=entity)

    async def insert_condition(self, condition_name, condition_bk):
        condition = ReverbProductCondition.create_condition(
            condition_name=condition_name,
            conditiion_bk=condition_bk)

        await self.__repository.insert(
            document=condition.to_dict())

        return condition
