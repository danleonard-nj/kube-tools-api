import json
from typing import Dict, List, Optional
from httpx import AsyncClient, get
from framework.clients.cache_client import CacheClientAsync
from models.googe_maps_models import GoogleMapsConfig, GooglePlaceDetails
from framework.crypto.hashing import md5
from framework.logger import get_logger

logger = get_logger(__name__)


class GooglePlacesClient:
    """Client for Google Places API to find businesses and locations"""

    def __init__(
        self,
        config: GoogleMapsConfig,
        http_client: AsyncClient,
        cache_client: CacheClientAsync
    ):
        self._config = config
        self._http_client = http_client
        self._cache_client = cache_client
        self._base_url = "https://maps.googleapis.com/maps/api/place"

    async def geocode_address(self, address: str) -> Optional[tuple]:
        """
        Convert an address to latitude and longitude using Google Geocoding API

        Args:
        address: Full address string to geocode

        Returns:
        Tuple of (latitude, longitude) or None if not found
        """
        if not address:
            return None

        def handle_response(resp):
            if resp['results']:
                logger.info(f'Geocoding successful for address: {address}: {resp}')
                loc = resp['results'][0]['geometry']['location']
                return (loc['lat'], loc['lng'])

        cache_key = f"geocode:{md5(address)}"
        cached_result = await self._cache_client.get_json(cache_key)
        if cached_result:
            return handle_response(cached_result)

        url = f'https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={self._config.api_key}'
        resp = await self._http_client.get(url)

        resp.raise_for_status()
        resp = resp.json()
        if resp['status'] != 'OK':
            raise Exception(f"Geocoding failed: {resp['status']} - {resp.get('error_message', '')}")

        await self._cache_client.set_json(
            key=cache_key,
            value=resp,
            ttl=72  # Cache for 1 hour
        )

        return handle_response(resp)
        raise Exception(f"Geocoding failed for address: {address}")

    async def nearby_search(self, location: str, place_type: str,
                            radius: int = 5000, keyword: Optional[str] = None) -> List[Dict]:
        """
        Search for places near a location

        Args:
            location: "lat,lng" format
            place_type: Google Places type (gas_station, grocery_or_supermarket, etc.)
            radius: Search radius in meters (max 50000)
            keyword: Additional keyword to filter results

        Returns:
            List of place objects from Google Places API
        """
        params = {
            "location": location,
            "radius": min(radius, 50000),  # Google's max radius
            "type": place_type,
            "key": self._config.api_key
        }

        if keyword:
            params["keyword"] = keyword

        # Cache key for this search
        cache_key = f"places-nearby-{md5(json.dumps(params, sort_keys=True))}"

        # Check cache first
        cached_result = await self._cache_client.get_json(cache_key)
        if cached_result:
            logger.info(f"Using cached places search for {cache_key}")
            return cached_result.get("results", [])

        # Make API call
        url = f"{self._base_url}/nearbysearch/json"
        response = await self._http_client.get(url, params=params)
        response.raise_for_status()

        data = response.json()

        if data.get("status") not in ["OK", "ZERO_RESULTS"]:
            error_msg = data.get("error_message", f"API returned status: {data.get('status')}")
            raise Exception(f"Google Places API error: {error_msg}")

        results = data.get("results", [])

        # Cache the results for 1 hour
        await self._cache_client.set_json(
            key=cache_key,
            value=data,
            ttl=3600  # 1 hour cache
        )

        logger.info(f"Found {len(results)} places for {place_type} near {location}")
        return results

    async def text_search(self, query: str, location: Optional[str] = None,
                          radius: Optional[int] = None) -> List[GooglePlaceDetails]:
        """
        Search for places using text query

        Args:
            query: Text search query like "walmart near philadelphia"
            location: "lat,lng" to bias results
            radius: Search radius in meters

        Returns:
            List of place objects
        """
        params = {
            "query": query,
            "key": self._config.api_key
        }

        if location:
            params["location"] = location

        if radius:
            params["radius"] = min(radius, 50000)

        # Cache key
        cache_key = f"places-text-{md5(json.dumps(params, sort_keys=True))}"

        # Check cache
        cached_result = await self._cache_client.get_json(cache_key)
        if cached_result:
            logger.info(f"Using cached text search for {cache_key}")
            return [GooglePlaceDetails(**place) for place in cached_result.get("results", [])]

        # Make API call
        url = f"{self._base_url}/textsearch/json"
        response = await self._http_client.get(url, params=params)
        response.raise_for_status()

        data = response.json()

        if data.get("status") not in ["OK", "ZERO_RESULTS"]:
            error_msg = data.get("error_message", f"API returned status: {data.get('status')}")
            raise Exception(f"Google Places API error: {error_msg}")

        results = data.get("results", [])

        # Cache results
        await self._cache_client.set_json(
            key=cache_key,
            value=data,
            ttl=3600
        )

        logger.info(f"Found {len(results)} places for text query: {query}")
        return [GooglePlaceDetails.model_validate(place) for place in results]

    async def get_place_details(self, place_id: str,
                                fields: List[str] = None) -> Optional[Dict]:
        """
        Get detailed information about a specific place

        Args:
            place_id: Google Places place_id
            fields: List of fields to return (name, rating, price_level, etc.)

        Returns:
            Place details object
        """
        if not fields:
            fields = [
                "name", "rating", "price_level", "formatted_address",
                "geometry", "opening_hours", "photos", "reviews",
                "address_components"  # Added to get city, state, etc.
            ]

        params = {
            "place_id": place_id,
            "fields": ",".join(fields),
            "key": self._config.api_key
        }

        # Cache key
        cache_key = f"place-details-{md5(json.dumps(params, sort_keys=True))}"

        # Check cache
        cached_result = await self._cache_client.get_json(cache_key)
        if cached_result:
            logger.info(f"Using cached place details for {place_id}")
            result = cached_result.get("result")
            if result:
                return GooglePlaceDetails(**result)
            return None

        # Make API call
        url = f"{self._base_url}/details/json"
        response = await self._http_client.get(url, params=params)
        response.raise_for_status()

        data = response.json()

        if data.get("status") != "OK":
            error_msg = data.get("error_message", f"API returned status: {data.get('status')}")
            raise Exception(f"Google Places API error: {error_msg}")

        result = data.get("result")

        # Cache result for longer (places don't change often)
        await self._cache_client.set_json(
            key=cache_key,
            value=data,
            ttl=86400  # 24 hour cache
        )

        if result:
            return GooglePlaceDetails(**result)
        return None

    async def find_places_along_route(self, waypoints: List[str], place_type: str,
                                      keyword: Optional[str] = None) -> List[Dict]:
        """
        Find places of a specific type along a route defined by waypoints

        Args:
            waypoints: List of "lat,lng" strings defining the route
            place_type: Type of place to search for
            keyword: Optional keyword filter

        Returns:
            List of places found along the route
        """
        all_places = []

        # Search around each waypoint
        for waypoint in waypoints:
            try:
                places = await self.nearby_search(
                    location=waypoint,
                    place_type=place_type,
                    radius=2000,  # 2km around each waypoint
                    keyword=keyword
                )
                all_places.extend(places)
            except Exception as e:
                logger.warning(f"Failed to search places near {waypoint}: {e}")
                continue

        # Remove duplicates based on place_id
        unique_places = []
        seen_place_ids = set()

        for place in all_places:
            place_id = place.get("place_id")
            if place_id and place_id not in seen_place_ids:
                unique_places.append(place)
                seen_place_ids.add(place_id)

        # Sort by rating (highest first)
        unique_places.sort(key=lambda p: p.get("rating", 0), reverse=True)

        return unique_places[:10]  # Return top 10


# Example usage
if __name__ == "__main__":
    import asyncio
    import os
    from models.googe_maps_models import GoogleMapsConfig
    from framework.clients.cache_client import CacheClientAsync

    async def test_places_client():
        config = GoogleMapsConfig(api_key=os.getenv("GOOGLE_MAPS_API_KEY"))

        # Mock cache client for testing
        class MockCacheClient:
            async def get_json(self, key: str):
                return None

            async def set_json(self, key: str, value: dict, ttl: int):
                pass

        async with AsyncClient() as http_client:
            cache_client = MockCacheClient()
            places_client = GooglePlacesClient(config, http_client, cache_client)

            # Test nearby search
            print("Testing nearby search for gas stations...")
            gas_stations = await places_client.nearby_search(
                location="39.9526,-75.1652",  # Philadelphia
                place_type="gas_station",
                radius=5000
            )

            print(f"Found {len(gas_stations)} gas stations:")
            for station in gas_stations[:3]:
                print(f"  - {station.get('name')} (Rating: {station.get('rating', 'N/A')})")

            # Test text search
            print("\nTesting text search...")
            walmarts = await places_client.text_search(
                query="walmart near philadelphia pa",
                location="39.9526,-75.1652",
                radius=10000
            )

            print(f"Found {len(walmarts)} Walmart stores:")
            for store in walmarts[:3]:
                print(f"  - {store.get('name')} at {store.get('formatted_address', 'Unknown address')}")

    # Run test
    asyncio.run(test_places_client())
