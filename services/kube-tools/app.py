from framework.abstractions.abstract_request import RequestContextProvider
from framework.serialization.serializer import configure_serializer
from framework.swagger.quart.swagger import Swagger
from quart import Quart
from routes import (acr_bp, api_event_history_bp, bank_bp, calendar_bp,
                    conversation_bp, google_bp, kubernetes_bp,
                    location_history_bp, mongo_backup_bp, podcasts_bp,
                    redis_bp, route_engine_bp, torrent_bp, usage_bp, weather_bp, robinhood_bp, route_engine_bp)
from utilities.provider import ContainerProvider
from dotenv import load_dotenv
load_dotenv()


app = Quart(__name__)

configure_serializer(app)

app.register_blueprint(podcasts_bp)
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
app.register_blueprint(torrent_bp)
app.register_blueprint(redis_bp)
app.register_blueprint(conversation_bp)
app.register_blueprint(robinhood_bp)
app.register_blueprint(route_engine_bp)

provider = ContainerProvider.get_service_provider()


@app.before_serving
async def startup():
    RequestContextProvider.initialize_provider(
        app=app)


swag = Swagger(app=app, title='kube-tools-api')
swag.configure()

if __name__ == '__main__':
    app.run(debug=True, port='5086')
