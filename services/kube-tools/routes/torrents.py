from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from domain.auth import AuthPolicy
from services.torrent_service import TorrentService

logger = get_logger(__name__)

torrent_bp = MetaBlueprint('torrent_bp', __name__)


@torrent_bp.configure('/api/torrents/search', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def post_search(container):
    service: TorrentService = container.resolve(TorrentService)

    query = request.args.get('q')
    page = request.args.get('page', 1)

    return await service.search(
        search_term=query,
        page=int(page))


@torrent_bp.configure('/api/torrents/magnet', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_magnet(container):
    service: TorrentService = container.resolve(TorrentService)

    body = await request.get_json()

    stub = body.get('stub')

    return await service.get_magnet_link(
        link_stub=stub)
