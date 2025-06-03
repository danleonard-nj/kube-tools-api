from domain.auth import AuthPolicy
from framework.di.service_provider import ServiceProvider
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint

from services.robinhood_service import RobinhoodService

robinhood_bp = MetaBlueprint('robinhood_bp', __name__)

logger = get_logger(__name__)


@robinhood_bp.configure('/api/robinhood/login', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def robinhood_login(container: ServiceProvider):
    service: RobinhoodService = container.resolve(RobinhoodService)

    return await service.login()


@robinhood_bp.configure('/api/robinhood/accounts', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def robinhood_accounts(container: ServiceProvider):
    service: RobinhoodService = container.resolve(RobinhoodService)

    return await service.get_account_info()


@robinhood_bp.configure('/api/robinhood/pulse/daily', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def robinhood_daily_pulse(container: ServiceProvider):
    service: RobinhoodService = container.resolve(RobinhoodService)

    return await service.generate_daily_pulse()


@robinhood_bp.configure('/api/robinhood/balance/sync', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def robinhood_balance_sync(container: ServiceProvider):
    """Sync current portfolio balance with bank service"""
    service: RobinhoodService = container.resolve(RobinhoodService)

    return await service.sync_portfolio_balance()
