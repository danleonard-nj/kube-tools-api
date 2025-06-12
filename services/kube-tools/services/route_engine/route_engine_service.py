import select
from typing import Dict, List, Optional
import itertools
from copy import deepcopy

import openai
from clients.google_places_client import GooglePlacesClient
from clients.google_route_data_client import GoogleRouteDataClient
from framework.exceptions.nulls import ArgumentNullException
from models.googe_maps_models import DirectionsRequestModel, GooglePlaceDetails, CustomDimensions
from models.google_maps_directions_response import DirectionsResponseModel
from models.openai_models import OpenAIConfig
from services.route_engine.route_parser import RouteParserHelper
from services.route_engine.route_selector import RouteSelectorHelper
from services.route_engine.waypoint_resolver import WaypointResolverHelper
from framework.logger import get_logger
# Import our new helper classes

logger = get_logger(__name__)


class RouteEngineService:
    """Main service for handling route requests with natural language processing"""

    def __init__(
        self,
        route_data_client: GoogleRouteDataClient,
        places_client: GooglePlacesClient,
        config: OpenAIConfig
    ):
        self._route_data_client = route_data_client
        self._places_client = places_client

        # Initialize OpenAI client
        openai_client = openai.AsyncOpenAI(api_key=config.api_key)

        # Initialize helper classes
        self._parser = RouteParserHelper(openai_client, places_client)
        self._waypoint_resolver = WaypointResolverHelper(openai_client, route_data_client, places_client)
        self._route_selector = RouteSelectorHelper(openai_client)

    # ========== CORE ROUTING METHODS ==========

    async def get_route(self, data: DirectionsRequestModel = None) -> DirectionsResponseModel:
        """Get a single route for given parameters"""
        logger.info(f"get_route called with data: {data}")

        ArgumentNullException.if_none_or_whitespace(data.origin, 'origin')
        ArgumentNullException.if_none_or_whitespace(data.destination, 'destination')

        if not data:
            logger.info("No valid routing parameters provided to get_route")
            raise Exception("No valid routing parameters provided")

        params = data.model_dump(exclude_none=True)
        logger.info(f"Calling _route_data_client.get_directions with params: {params}")

        result = await self._route_data_client.get_directions(params)
        return result

    async def get_route_options(self, data: DirectionsRequestModel = None) -> List[Dict]:
        """Get multiple route options with analysis"""
        logger.info(f"get_route_options called with data: {data}")

        ArgumentNullException.if_none_or_whitespace(data.origin, 'origin')
        ArgumentNullException.if_none_or_whitespace(data.destination, 'destination')

        if not data:
            logger.info("No valid routing parameters provided to get_route_options")
            raise Exception("No valid routing parameters provided")

        params = data.model_dump(exclude_none=True)
        # Ensure alternatives is set to True
        params["alternatives"] = True
        logger.info(f"Calling _route_data_client.get_directions with params: {params}")

        directions = await self._route_data_client.get_directions(params)

        # Robustly extract routes from the response
        if not hasattr(directions, 'routes') or not directions.routes:
            logger.warning('No valid route exists for the provided prompt or no routes attribute in response')
            raise Exception(f'No valid route exists for the provided prompt')

        if len(directions.routes) == 1:
            logger.warning('Only one route returned from Google Directions API despite alternatives=True')

        options = self._route_selector.analyze_route_options(directions.routes)
        logger.info(f"Number of route options returned: {len(options)}")
        return options

    # ========== NATURAL LANGUAGE ROUTING ==========

    async def _normalize_address(self, address: str) -> GooglePlaceDetails:
        """
        Normalize an address using Google Places text search. Returns the formatted address.
        Raises Exception if no result is found.
        """
        results = await self._places_client.text_search(query=address)
        if not results:
            raise Exception(f"Could not normalize address: '{address}'. No results from Google Places.")
        # Use the first result's formatted address
        first_result = results[0] if results else None

        return first_result

    async def get_route_with_natural_language(self, prompt: str) -> Dict:
        """
        Main method that handles full natural language routing with waypoints, now supports all waypoint combinations.
        """
        # Step 1: Parse natural language to structured request + waypoint requirements
        parsed_data = await self._parser.parse_prompt_to_directions_request(prompt)
        model_data = parsed_data["model"]
        # --- Use CustomDimensions model for custom_dimensions ---
        custom_dimensions = parsed_data["unwrapped_details"]
        if not isinstance(custom_dimensions, CustomDimensions):
            # If it's a dict, coerce to model
            custom_dimensions = CustomDimensions(**custom_dimensions) if isinstance(custom_dimensions, dict) else CustomDimensions()
        all_waypoint_options = parsed_data.get("all_waypoint_options", [])
        excluded_routes = custom_dimensions.excluded_routes or []
        logger.info(f"Parsed model_data: {model_data}")
        logger.info(f"Custom dimensions: {custom_dimensions}")

        diagnostics = {
            "parsed_model_data": model_data.copy(),
            "custom_dimensions": custom_dimensions.model_dump(),
            "waypoint_resolution_log": [],
            "final_model_data": None,
            "route_options": None,
            "original_address": {
                "origin": model_data.get("origin"),
                "destination": model_data.get("destination")
            },
            "excluded_routes": excluded_routes,
            "errors": [],
        }

        # Normalize addresses
        try:
            origin = await self._normalize_address(model_data["origin"])
            model_data["origin"] = origin.formatted_address
            destination = await self._normalize_address(model_data["destination"])
            model_data["destination"] = destination.formatted_address
        except Exception as e:
            diagnostics["errors"].append(f"Address normalization error: {str(e)}")
            raise

        # Step 2: Extract waypoint requirements from custom_dimensions
        waypoint_requirements = await self._waypoint_resolver.extract_waypoint_requirements(
            prompt, custom_dimensions.model_dump()
        )
        logger.info(f"Extracted {len(waypoint_requirements)} waypoint requirements")

        # Step 3: Resolve waypoint requirements to actual places
        if waypoint_requirements:
            try:
                await self._waypoint_resolver.resolve_waypoints(
                    waypoint_requirements,
                    model_data["origin"],
                    model_data["destination"]
                )
            except Exception as e:
                diagnostics["errors"].append(f"Error resolving waypoints: {str(e)}")

            # Step 4: Insert resolved waypoints into model, skipping excluded_routes
            try:
                # Remove any waypoints that are in excluded_routes
                filtered_requirements = [req for req in waypoint_requirements if getattr(req, 'place_type', None) not in excluded_routes and getattr(req, 'specifics', None) not in excluded_routes]
                model_data = self._waypoint_resolver.insert_waypoints_into_model(
                    model_data, filtered_requirements
                )
                logger.info(f"Final model_data with waypoints: {model_data}")
                diagnostics["final_model_data"] = model_data.copy()
            except Exception as e:
                diagnostics["errors"].append(f"Error inserting waypoints: {str(e)}")
        else:
            diagnostics["final_model_data"] = model_data.copy()

        # Step 5: Get route options for all waypoint combinations
        try:
            all_routes = await self.get_route_options_for_all_waypoint_combinations(model_data, all_waypoint_options)
            # Flatten all route options for LLM selection
            all_route_options = []
            for route_set in all_routes:
                for route in route_set.get('routes', []):
                    # Attach waypoints to each route for context
                    route['waypoints'] = route_set.get('waypoints', [])
                    all_route_options.append(route)
            # --- Filter out routes that include excluded_routes ---

            def route_includes_excluded(route):
                # Check summary, waypoints, and step instructions for excluded_routes
                summary = route.get('summary', '').lower()
                waypoints = [str(w).lower() for w in route.get('waypoints', [])]
                steps = []
                for leg in route.get('legs', []):
                    steps.extend(leg.get('steps', []))
                step_texts = ' '.join([step.get('html_instructions', '').lower() for step in steps])
                for ex in excluded_routes:
                    ex_l = ex.lower()
                    if ex_l in summary or any(ex_l in w for w in waypoints) or ex_l in step_texts:
                        return True
                return False
            all_route_options = [r for r in all_route_options if not route_includes_excluded(r)]
            diagnostics["route_options"] = all_route_options
        except Exception as e:
            diagnostics["errors"].append(f"Error getting route options: {str(e)}")
            all_route_options = []

        # Step 6: Use ChatGPT to select best route considering original request
        try:
            def enrich_route_dict(route):
                return {
                    **route,
                    "summary": route.get("summary") or route.get("legs", [{}])[0].get("summary", ""),
                    "distance_km": route.get("legs", [{}])[0].get("distance", {}).get("value", 0) / 1000,
                    "duration_minutes": route.get("legs", [{}])[0].get("duration", {}).get("value", 0) / 60,
                    "has_tolls": any("toll" in (step.get("html_instructions", "").lower()) for step in route.get("legs", [{}])[0].get("steps", [])),
                    "highway_percentage": 0.0,
                    "via_waypoints": route.get("waypoints", []),
                }
            enriched_llm_route_options = [enrich_route_dict(r) for r in all_route_options]
            selected_route_model = await self._route_selector.select_best_route_with_llm(
                enriched_llm_route_options, prompt, waypoint_requirements
            )
            selected_route = all_route_options[selected_route_model.index - 1] if all_route_options else None
        except Exception as e:
            diagnostics["errors"].append(f"Error selecting best route: {str(e)}")
            selected_route = None
            raise

        return {
            "selected_route": {
                'summary': getattr(selected_route_model, 'summary', None),
                'route': selected_route
            },
            "waypoint_requirements": [req.__dict__ for req in waypoint_requirements],
            "alternatives_considered": len(all_route_options),
            "original_prompt": prompt,
            "diagnostics": diagnostics,
            "directions_url": self._route_data_client.generate_directions_url(model_data)
        }

    async def get_route_options_for_all_waypoint_combinations(self, model_data: dict, all_waypoint_options: list) -> list:
        """
        Given model_data and all_waypoint_options (list of lists of candidate waypoints),
        generate all combinations, call get_route_options for each, and return all results.
        """
        all_routes = []
        if not all_waypoint_options:
            # No waypoints, just call once
            directions_request = DirectionsRequestModel.model_validate(model_data)
            directions_request.alternatives = True
            try:
                route_options = await self.get_route_options(directions_request)
                all_routes.append({
                    'waypoints': [],
                    'routes': [r.model_dump() if hasattr(r, 'model_dump') else r for r in route_options]
                })
            except Exception as e:
                all_routes.append({'waypoints': [], 'error': str(e)})
            return all_routes

        for combo in itertools.product(*all_waypoint_options):
            combo_waypoints = list(combo)
            combo_model_data = deepcopy(model_data)
            combo_model_data['waypoints'] = combo_waypoints
            directions_request = DirectionsRequestModel.model_validate(combo_model_data)
            directions_request.alternatives = True
            try:
                route_options = await self.get_route_options(directions_request)
                all_routes.append({
                    'waypoints': combo_waypoints,
                    'routes': [r.model_dump() if hasattr(r, 'model_dump') else r for r in route_options]
                })
            except Exception as e:
                all_routes.append({'waypoints': combo_waypoints, 'error': str(e)})
        return all_routes

    # ========== LEGACY SUPPORT ==========

    async def parse_prompt_to_directions_request(self, prompt: str):
        """
        Legacy method - delegates to parser helper
        Uses ChatGPT to parse a natural language prompt into a DirectionsRequestModel and a list of unmapped details.
        Returns (DirectionsRequestModel, List[str])
        """
        return await self._parser.parse_prompt_to_directions_request(prompt)
