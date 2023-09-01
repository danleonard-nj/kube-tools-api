from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from domain.auth import AuthPolicy
from services.dead_man_switch_service import DeadManSwitchService

logger = get_logger(__name__)

dead_man_bp = MetaBlueprint('dead_man_bp', __name__)


@dead_man_bp.configure('/api/dms/poll', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_dms_poll(container):
    service: DeadManSwitchService = container.resolve(DeadManSwitchService)

    return await service.poll()


@dead_man_bp.configure('/api/dms/disarm', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_dms_disarm(container):
    service: DeadManSwitchService = container.resolve(DeadManSwitchService)

    return await service.disarm_switch()