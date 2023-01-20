from framework.abstractions.abstract_request import RequestContextProvider
from framework.logger.providers import get_logger
from framework.serialization.serializer import configure_serializer
from framework.swagger.quart.swagger import Swagger
from quart import Quart

from routes.acr import acr_bp
from routes.health import health_bp
from routes.location import location_bp
from routes.mongo_backup import mongo_backup_bp
from routes.podcasts import podcasts_bp
from routes.location_history import location_history_bp
from routes.usage import usage_bp
from routes.webhooks import webhook_bp
from routes.walle import wallet_bp
from utilities.provider import ContainerProvider
from framework.dependency_injection.provider import InternalProvider
from utilities.utils import getattr_or_none

logger = get_logger(__name__)
app = Quart(__name__)


configure_serializer(app)


app.register_blueprint(podcasts_bp)
app.register_blueprint(acr_bp)
app.register_blueprint(health_bp)
app.register_blueprint(usage_bp)
app.register_blueprint(mongo_backup_bp)
app.register_blueprint(location_bp)
app.register_blueprint(location_history_bp)
app.register_blueprint(wallet_bp)
app.register_blueprint(webhook_bp)

ContainerProvider.initialize_provider()
InternalProvider.bind(ContainerProvider.get_service_provider())


@app.before_serving
async def startup():
    RequestContextProvider.initialize_provider(
        app=app)


@app.errorhandler(Exception)
def error_handler(e):
    app.logger.exception('Failed')
    message = {'error': str(e)}
    return message, getattr_or_none(
        obj=e,
        name='code') or 500


swag = Swagger(app=app, title='kube-tools-api')
swag.configure()

if __name__ == '__main__':
    app.run(debug=True, port='5086')
