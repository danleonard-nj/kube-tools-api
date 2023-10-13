import logging

from framework.abstractions.abstract_request import RequestContextProvider
from framework.di.static_provider import InternalProvider
from framework.logger.providers import get_logger
from framework.serialization.serializer import configure_serializer
from framework.swagger.quart.swagger import Swagger
from quart import Quart

from routes.acr import acr_bp
from routes.api_event_history import api_event_history_bp
from routes.bank import bank_bp
from routes.calendar import calendar_bp
from routes.dead_man import dead_man_bp
from routes.google import google_bp
from routes.journal import journal_bp
from routes.kubernetes import kubernetes_bp
from routes.location_history import location_history_bp
from routes.mongo_backup import mongo_backup_bp
from routes.podcasts import podcasts_bp
from routes.torrents import torrent_bp
from routes.usage import usage_bp
from routes.vesting import vesting_bp
from routes.weather import weather_bp
from utilities.provider import ContainerProvider
from utilities.utils import deprecate_logger

deprecate_logger.info('testing deprected logger')

logger = get_logger(__name__)
app = Quart(__name__)


def getattr_or_none(obj, name):
    if hasattr(obj, name):
        return getattr(obj, name)
    return None


configure_serializer(app)


app.register_blueprint(podcasts_bp)
app.register_blueprint(vesting_bp)
app.register_blueprint(acr_bp)
app.register_blueprint(kubernetes_bp)
app.register_blueprint(usage_bp)
app.register_blueprint(mongo_backup_bp)
app.register_blueprint(google_bp)
app.register_blueprint(location_history_bp)
app.register_blueprint(calendar_bp)
app.register_blueprint(api_event_history_bp)
app.register_blueprint(bank_bp)
app.register_blueprint(weather_bp)
app.register_blueprint(journal_bp)
app.register_blueprint(torrent_bp)
app.register_blueprint(dead_man_bp)

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
