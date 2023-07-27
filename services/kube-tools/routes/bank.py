from framework.clients.feature_client import FeatureClientAsync
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from domain.auth import AuthPolicy
from domain.features import Feature
from services.acr_purge_service import AcrPurgeService
from services.bank_service import BankService

logger = get_logger(__name__)

bank_bp = MetaBlueprint('bank_bp', __name__)


@bank_bp.configure('/api/bank/balances/<key>', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_bank_balance(container, key):
    service: BankService = container.resolve(BankService)

    return await service.get_balance(
        bank_key=key)


@bank_bp.configure('/api/bank/balances', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_bank_balances(container):
    service: BankService = container.resolve(BankService)

    return await service.get_balances()


@bank_bp.configure('/api/bank/sync', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_sync(container):
    service: BankService = container.resolve(BankService)

    return await service.run_sync()


@bank_bp.configure('/api/bank/transactions/sync', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_transactions_sync(container):
    service: BankService = container.resolve(BankService)

    return await service.sync_transactions()


@bank_bp.configure('/api/bank/webhook', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_bank_webhook(container):
    service: BankService = container.resolve(BankService)

    body = await request.get_json()

    return await service.handle_webhook(
        data=body)
