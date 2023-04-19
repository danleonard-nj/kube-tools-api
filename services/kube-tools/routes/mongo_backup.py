from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from services.mongo_backup_service import MongoBackupService

mongo_backup_bp = MetaBlueprint('mongo_backup_bp', __name__)


@mongo_backup_bp.configure('/api/mongo/backup', methods=['POST'], auth_scheme='default')
async def export_backup(container):
    service: MongoBackupService = container.resolve(
        MongoBackupService)

    days = request.args.get('purge_days', 7)

    result = await service.export_backup(
        purge_days=int(days))

    return result


@mongo_backup_bp.configure('/api/mongo/backup/purge', methods=['POST'], auth_scheme='default')
async def post_mongo_backup_purge(container):
    service: MongoBackupService = container.resolve(
        MongoBackupService)

    days = request.args.get('purge_days', 7)

    result = await service.purge_exports(
        purge_days=int(days))

    return result
