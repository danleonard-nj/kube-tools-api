import json
import os
from urllib.parse import urlencode
from httpx import AsyncClient
from typing import Dict, List, Optional, Union, Literal
from dataclasses import dataclass
from pydantic import BaseModel, Field
from framework.clients.cache_client import CacheClientAsync
from models.googe_maps_models import GoogleMapsConfig
from framework.crypto.hashing import md5
from models.google_maps_directions_response import DirectionsResponseModel
from framework.logger import get_logger

logger = get_logger(__name__)


class GoogleRouteDataClient:
    """Client for fetching Google Maps route data (minimal logic, just API interaction)"""

    def __init__(
        self,
        config: GoogleMapsConfig,
        http_client: AsyncClient,
        cache_client: CacheClientAsync
    ):
        self._config = config
        self._http_client = http_client
        self._cache_client = cache_client

    async def get_directions(self, params: Dict) -> DirectionsResponseModel:
        """Call Google Maps Directions API and return parsed response model."""
        logger.info(f"get_directions called with params: {params}")
        query_params = params.copy()
        logger.info(f"Initial query_params copy: {query_params}")
        # Convert list params to pipe-delimited strings as required by Google Maps API
        for k in ["avoid", "waypoints"]:
            v = query_params.get(k)
            logger.info(f"Processing param '{k}': {v}")
            if isinstance(v, list):
                query_params[k] = "|".join(v)
                logger.info(f"Converted list param '{k}' to pipe-delimited string: {query_params[k]}")
        if "alternatives" in query_params:
            # Google expects 'alternatives' as 'true'/'false' string
            logger.info(f"Original 'alternatives' value: {query_params['alternatives']}")
            query_params["alternatives"] = str(query_params["alternatives"]).lower()
            logger.info(f"Converted 'alternatives' to string: {query_params['alternatives']}")
        query_params["key"] = self._config.api_key
        logger.info(f"Final query_params for request: {query_params}")
        url = "https://maps.googleapis.com/maps/api/directions/json"
        logger.info(f"Request URL: {url}")
        key = f"google-maps-directions-response-{md5(f'{url}-{json.dumps(query_params, sort_keys=True, default=str)}')}"
        logger.info(f"Cache key generated: {key}")
        cached_response = await self._cache_client.get_json(key)
        if cached_response:
            logger.info(f"Using cached response for {key}")
            return DirectionsResponseModel.model_validate(cached_response)
        logger.info(f"No cached response found. Making HTTP request to Google Maps Directions API.")
        response = await self._http_client.get(url, params=query_params)
        logger.info(f"HTTP response status: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        logger.info(f"Response JSON: {json.dumps(data, indent=2)[:1000]}")  # Log first 1000 chars
        if data.get("status") != "OK":
            error_msg = data.get("error_message", f"API returned status: {data.get('status')}")
            logger.info(f"Google Maps API error: {error_msg}")
            raise Exception(f"Google Maps API error: {error_msg}: Params: {params}: Response: {data}")
        await self._cache_client.set_json(
            key=key,
            value=data,
            ttl=60  # Cache for 1 hour
        )
        logger.info(f"Response cached with key: {key}")
        return DirectionsResponseModel.model_validate(data)

    def generate_directions_url(self, params: Dict) -> str:
        """Generate a Google Maps directions URL from the given parameters."""
        base_url = "https://www.google.com/maps/dir/?api=1"
        url_params = {}
        # Google Maps web expects 'origin', 'destination', 'waypoints', 'travelmode', 'avoid', 'units', 'region', 'alternatives'
        if 'origin' in params:
            url_params['origin'] = params['origin']
        if 'destination' in params:
            url_params['destination'] = params['destination']
        if 'waypoints' in params:
            waypoints = params['waypoints']
            if isinstance(waypoints, list):
                url_params['waypoints'] = '|'.join(waypoints)
            else:
                url_params['waypoints'] = waypoints
        if 'travel_mode' in params:
            url_params['travelmode'] = params['travel_mode']
        elif 'travelmode' in params:
            url_params['travelmode'] = params['travelmode']
        if 'avoid' in params:
            avoid = params['avoid']
            if isinstance(avoid, list):
                url_params['avoid'] = '|'.join(avoid)
            else:
                url_params['avoid'] = avoid
        if 'units' in params:
            url_params['units'] = params['units']
        if 'region' in params:
            url_params['region'] = params['region']
        if 'alternatives' in params:
            url_params['alternatives'] = str(params['alternatives']).lower()

        params['alternatives'] = True
        # Build the URL
        return f"{base_url}&{urlencode(url_params)}"
