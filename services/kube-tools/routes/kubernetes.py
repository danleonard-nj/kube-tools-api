from quart import Blueprint

kubernetes_bp = Blueprint('kubernetes_bp', __name__)


@kubernetes_bp.route('/api/health/alive')
def alive():
    return {'status': 'ok'}, 200


@kubernetes_bp.route('/api/health/ready')
def ready():
    return {'status': 'ok'}, 200
