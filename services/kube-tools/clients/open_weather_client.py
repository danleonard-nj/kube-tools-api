from framework.configuration import Configuration
from framework.logger import get_logger
from framework.uri import build_url
from httpx import AsyncClient

from domain.weather import GetWeatherQueryParams

logger = get_logger(__name__)


class OpenWeatherClient:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient
    ):
        self.__base_url = configuration.openweather.get('base_url')
        self.__api_key = configuration.openweather.get('api_key')

        self.__http_client = http_client

    async def get_weather_by_zip(
        self,
        zip_code: str
    ):
        logger.info(f'Getting weather for {zip_code}')
        # API request parameters
        query_params = GetWeatherQueryParams(
            zip_code=zip_code,
            api_key=self.__api_key)

        logger.info(f'Request: {query_params.to_dict()}')

        endpoint = build_url(
            base=f'{self.__base_url}/data/2.5/weather',
            **query_params.to_dict())

        logger.info(f'Endpoint: {endpoint}')

        response = await self.__http_client.get(
            url=endpoint)

        logger.info(f'Response status: {response.status_code}')

        data = response.json()

        logger.info(f'Weather for {zip_code}: {data}')

        return data

    async def get_forecast(
        self,
        zip_code: str
    ):
        query_params = GetWeatherQueryParams(
            zip_code=zip_code,
            api_key=self.__api_key)

        endpoint = build_url(
            base=f'{self.__base_url}/data/2.5/forecast',
            **query_params.to_dict())

        response = await self.__http_client.get(
            url=endpoint)

        logger.info(f'Response status: {response.status_code}')

        data = response.json()

        logger.info(f'Weather for {zip_code}: {data}')

        return data

        # To fetch the 10-day weather forecast for a given US postal code, you can use the OpenWeatherMap API. You will need an API key to access the weather data, so make sure you have one before proceeding. Here's an example script:


# # Function to get the weather forecast for a given postal code
# def get_weather_forecast(postal_code):
#     # API endpoint URL
#     url = f"http://api.openweathermap.org/data/2.5/forecast?zip={postal_code},us&units=imperial&appid={api_key}"

#     try:
#         # Send a GET request to the API
#         response = requests.get(url)
#         data = json.loads(response.text)

#         # Extract the weather forecast
#         forecast = data["list"][:10]

#         # Print the forecast
#         for i, weather in enumerate(forecast, 1):
#             # Extract relevant information from the forecast
#             date = weather["dt_txt"]
#             temperature = weather["main"]["temp"]
#             description = weather["weather"][0]["description"]

#             # Print the forecast for each day
#             print(f"Day {i}: {date} - Temperature: {temperature}°F, Description: {description}")

#     except requests.exceptions.RequestException as error:
#         print("Error fetching weather forecast:", error)


# # Get the postal code from the user
# postal_code = input("Enter US postal code: ")

# # Fetch and display the weather forecast
# get_weather_forecast(postal_code)
# ```

# Make sure to replace `"YOUR_API_KEY"` with your actual OpenWeatherMap API key. The script prompts the user to enter a US postal code and then fetches and displays the 10-day weather forecast for that location.
