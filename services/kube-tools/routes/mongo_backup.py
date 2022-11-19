from services.mongo_backup_service import MongoBackupService
from utilities.meta import MetaBlueprint
from quart import request

mongo_backup_bp = MetaBlueprint('mongo_backup_bp', __name__)


@mongo_backup_bp.configure('/api/mongo/backup', methods=['POST'], auth_scheme='default')
async def export_backup(container):
    service: MongoBackupService = container.resolve(
        MongoBackupService)

    days = request.args.get('purge_days', 7)

    data = await service.export_backup(
        purge_days=days)

    return data
