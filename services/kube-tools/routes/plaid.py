
from quart import jsonify, request
from framework.rest.blueprints.meta import MetaBlueprint
from services.banking.plaid_sync_service import PlaidSyncService
from domain.auth import AuthPolicy
from services.plaid_usage_service import PlaidUsageService

plaid_bp = MetaBlueprint('plaid_bp', __name__)


@plaid_bp.configure('/api/plaid/sync', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def get_plaid_sync(container):
    service: PlaidSyncService = container.resolve(PlaidSyncService)
    await service.sync_all()
    return jsonify({"status": "complete"}), 200


# Fetch all accounts endpoint
@plaid_bp.configure('/api/plaid/accounts', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_plaid_accounts(container):
    service: PlaidSyncService = container.resolve(PlaidSyncService)
    accounts = await service.get_account_balances()
    # Optionally filter by account_id if provided
    account_id = request.args.get('account_id')
    if account_id:
        accounts = [a for a in accounts if a.account_id == account_id]
    return jsonify([a.model_dump() for a in accounts])


# Fetch transactions endpoint
@plaid_bp.configure('/api/plaid/transactions', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_plaid_transactions(container):
    service: PlaidSyncService = container.resolve(PlaidSyncService)
    account_id = request.args.get('account_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    # Convert dates to datetime if provided
    from datetime import datetime
    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    if not account_id:
        return jsonify({"error": "account_id is required"}), 400
    txs = await service.get_transactions(account_id=account_id, start_date=start_dt, end_date=end_dt)
    return jsonify([t.model_dump() for t in txs])


@plaid_bp.configure('/api/plaid/usage', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_plaid_usage(container):
    service: PlaidUsageService = container.resolve(PlaidUsageService)
    usage_data = await service.get_usage_data(days_back=30)
    if usage_data is None:
        return jsonify({"error": "Failed to retrieve usage data"}), 500
    return jsonify(usage_data), 200
