from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from domain.auth import AuthPolicy
from services.vesting_schedule_service import VestingScheduleService
from services.weather_service import WeatherService

logger = get_logger(__name__)

vesting_bp = MetaBlueprint('vesting_bp', __name__)


@vesting_bp.configure('/api/vesting', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_vesting_schedule(container):
    service: VestingScheduleService = container.resolve(VestingScheduleService)

    date = request.args.get('date')

    return await service.get_vesting_schedule(
        date=date)
