import uuid
from datetime import datetime

from framework.logger import get_logger

from data.wr_repository import WellnessCheckRepository, WellnessReplyRepository
from domain.wr import WellnessCheck, WellnessReply, WellnessReplyRequest

logger = get_logger(__name__)


class WellnessResponseService:
    def __init__(
        self,
        check_repository: WellnessCheckRepository,
        reply_repository: WellnessReplyRepository
    ):
        self.__check_repository = check_repository
        self.__reply_repository = reply_repository

    async def get_checks(
        self
    ):
        logger.info(F'Fetch alert recipients')

        entities = await self.__recipient_repository.get_all()

        recipients = [WellnessCheck.from_entity(data=entity)
                      for entity in entities]

        return recipients

    async def create_check(
        self,
        name,
        threshold,
        recipient,
        recipient_type,
        message: str
    ):
        logger.info(f'Creating wellness check: {name}')

        existing = await self.__check_repository.get({
            'name': name
        })

        if existing is not None:
            raise Exception(f"A check with the name '{name}' already exists")

        logger.info(f'Sanitizing phone number')

        check_id = str(uuid.uuid4())

        logger.info(f'Creating check: {check_id}')

        # Create the check
        check = WellnessCheck(
            check_id=check_id,
            name=name,
            threshold=threshold,
            recipient=recipient,
            recipient_type=recipient_type,
            message=message,
            created_date=datetime.now())

        await self.__check_repository.insert(
            document=check.to_dict())

        return check

    async def poll(
        self
    ):
        entities = await self.__check_repository.get_all()

        checks = [WellnessCheck.from_entity(data=entity)
                  for entity in entities]

        return checks

    async def handle_response(
        self,
        reply_request: WellnessReplyRequest
    ):
        logger.info(f'Handling inbound SMS response')

        reply = WellnessReply.from_respose(
            form=reply_request.form)

        logger.info(f'Sender: {reply.sender}: {reply.body}')

        entity = reply.to_dict()

        await self.__reply_repository.insert(
            document=entity)
