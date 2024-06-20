from domain.auth import AuthPolicy
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from framework.exceptions.nulls import none_or_whitespace
from services.weather_service import WeatherService
from framework.exceptions.rest import HttpException

logger = get_logger(__name__)

weather_bp = MetaBlueprint('weather_bp', __name__)


@weather_bp.configure('/api/weather', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_weather(container):
    service: WeatherService = container.resolve(WeatherService)

    zip_code = request.args.get('zip_code')

    if none_or_whitespace(zip_code):
        raise HttpException('Zip code is required', 400)

    return await service.get_weather_by_zip(
        zip_code=zip_code)


@weather_bp.configure('/api/weather/forecast', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_forecast(container):
    service: WeatherService = container.resolve(WeatherService)

    zip_code = request.args.get('zip_code')

    if none_or_whitespace(zip_code):
        raise HttpException('Zip code is required', 400)

    return await service.get_forecast(
        zip_code=zip_code)
