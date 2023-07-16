# To get a 10-day daily weather forecast for a given zip code in Python, you can use the OpenWeatherMap API. Here's an example script that uses the `requests` library to make the API call:

# ```python
import requests


def get_weather_forecast(zip_code):
    # Replace with your OpenWeatherMap API key
    api_key = 'e1dad3b0b92cbab6601ce47b5c77c1ae'
    base_url = 'http://api.openweathermap.org/data/2.5/forecast'

    # Make API request
    params = {
        'zip': zip_code,
        'units': 'imperial',  # Use 'metric' for Celsius
        'appid': api_key
    }
    response = requests.get(base_url, params=params)

    # Process API response
    if response.status_code == 200:
        weather_data = response.json()
        forecast = weather_data.get('list')[:10]  # Extract first 10 days
        return forecast
    else:
        print('Error: Failed to retrieve weather forecast')
        return None


# Set the zip code for which you want to get the forecast
zip_code = '85032'  # Replace with desired zip code

# Get the weather forecast
forecast = get_weather_forecast(zip_code)

if forecast:
    # Print the result
    print(f'10-Day Weather Forecast for {zip_code}:')
    for day in forecast:
        date = day['dt_txt']
        weather = day['weather'][0]['description']
        temp_min = day['main']['temp_min']
        temp_max = day['main']['temp_max']
        print(f'{date}: {weather}, Min Temp: {temp_min}F, Max Temp: {temp_max}F')
else:
    print('Failed to get weather forecast')
# ```

# Make sure to replace `'YOUR_API_KEY'` with your actual OpenWeatherMap API key and `'YOUR_ZIP_CODE'` with the desired zip code you want to get the forecast for.
