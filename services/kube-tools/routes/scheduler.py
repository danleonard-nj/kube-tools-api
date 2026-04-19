from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from domain.scheduler import CronGenerateRequest
from services.scheduler_service import SchedulerService

logger = get_logger(__name__)

scheduler_bp = MetaBlueprint('scheduler_bp', __name__)


@scheduler_bp.configure('/api/scheduler/cron/generate', methods=['POST'], auth_scheme='default')
async def post_cron_generate(container):
    """Generate and parse a CRON expression from a plain-language prompt.

    Request body:
    {
        "prompt": "every weekday at 9am"
    }
    """
    service: SchedulerService = container.resolve(SchedulerService)

    body = await request.get_json(silent=True) or {}
    req = CronGenerateRequest.model_validate(body)

    logger.info(f'CRON generate request: {req.prompt!r}')

    result = await service.generate_cron(prompt=req.prompt)

    return result.model_dump()
