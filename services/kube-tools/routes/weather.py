from domain.auth import AuthPolicy
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from services.weather_service import WeatherService

logger = get_logger(__name__)

weather_bp = MetaBlueprint('weather_bp', __name__)


@weather_bp.configure('/api/weather', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_weather(container):
    service: WeatherService = container.resolve(WeatherService)

    zip_code = request.args.get('zip_code')

    return await service.get_weather_by_zip(
        zip_code=zip_code)


@weather_bp.configure('/api/weather/forecast', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_forecast(container):
    service: WeatherService = container.resolve(WeatherService)

    zip_code = request.args.get('zip_code')

    return await service.get_forecast(
        zip_code=zip_code)
