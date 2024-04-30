from typing import Dict

from domain.auth import AuthPolicy
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from services.bank_service import BankService
from utilities.utils import parse_timestamp

logger = get_logger(__name__)

bank_bp = MetaBlueprint('bank_bp', __name__)


def get_transactions_query_params() -> Dict:
    start_timestamp = request.args.get('start_timestamp')
    end_timestamp = request.args.get('end_timestamp')

    bank_keys = request.args.to_dict(flat=False).get('bank_key')

    return {
        'start_timestamp': parse_timestamp(start_timestamp) if start_timestamp is not None else None,
        'end_timestamp': parse_timestamp(end_timestamp) if end_timestamp is not None else None,
        'bank_keys': bank_keys if bank_keys is not None else list(),
        'group_institutions': request.args.get('group_institutions', 'false').lower() == 'true'
    }


def get_balance_history_query_params() -> Dict:
    start_timestamp = request.args.get('start_timestamp')
    end_timestamp = request.args.get('end_timestamp')
    bank_keys = request.args.to_dict(flat=False).get('bank_key')

    return {
        'start_timestamp': parse_timestamp(start_timestamp) if start_timestamp is not None else None,
        'end_timestamp': parse_timestamp(end_timestamp) if end_timestamp is not None else None,
        'bank_keys': bank_keys if bank_keys is not None else list(),
        'group_institutions': request.args.get('group_institutions', 'false').lower() == 'true'
    }


def get_transaction_sync_query_params() -> dict:
    return {
        'days_back': int(request.args.get('days_back', 7)),
        'include_transactions': request.args.get('include_transactions', '').lower() == 'true'
    }


def get_balance_sync_query_params() -> dict:
    return {
        'run_async': request.args.get('run_async', '').lower() == 'true',
    }


@bank_bp.configure('/api/bank/balances/<key>', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_bank_balance(container, key):
    service: BankService = container.resolve(BankService)

    return await service.get_balance(
        bank_key=key)


@bank_bp.configure('/api/bank/balances/history', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_bank_balance_history(container):
    service: BankService = container.resolve(BankService)

    params = get_balance_history_query_params()

    return await service.get_balance_history(
        **params)


@bank_bp.configure('/api/bank/balances', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_bank_balances(container):
    service: BankService = container.resolve(BankService)

    return await service.get_balances()


@bank_bp.configure('/api/bank/sync', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_sync(container):
    service: BankService = container.resolve(BankService)

    params = get_balance_sync_query_params()

    return await service.run_balance_sync(
        **params)


@bank_bp.configure('/api/bank/transactions/sync', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_transactions_sync(container):
    service: BankService = container.resolve(BankService)

    params = get_transaction_sync_query_params()

    return await service.run_transaction_sync(
        **params)


@bank_bp.configure('/api/bank/transactions', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_transactions(container):
    service: BankService = container.resolve(BankService)

    params = get_transactions_query_params()

    return await service.get_transactions(
        **params)
