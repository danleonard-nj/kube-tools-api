import json
import openai
from typing import Dict, List
from dataclasses import dataclass
from domain.gpt import GPTModel
from clients.google_route_data_client import GoogleRouteDataClient
from framework.logger import get_logger
from clients.google_places_client import GooglePlacesClient

logger = get_logger(__name__)


@dataclass
class WaypointRequirement:
    """Represents a waypoint requirement extracted from natural language"""
    place_type: str      # "gas station", "grocery store", etc.
    direction: str       # "there", "back", "both"
    specifics: str       # "walmart", "shell", "cheap", etc.
    priority: int = 1    # 1=required, 2=preferred, 3=optional
    resolved_place: Dict = None


class WaypointResolverHelper:
    """Handles waypoint requirement extraction, resolution, and validation"""

    def __init__(self, openai_client: openai.AsyncOpenAI,
                 route_data_client: GoogleRouteDataClient,
                 places_client: GooglePlacesClient):
        self._open_ai_client = openai_client
        self._route_data_client = route_data_client
        self._places_client = places_client

    def _strip_json_code_block(self, response: str) -> str:
        """Helper to remove code block markers (```json ... ```) from a response string."""
        resp = response.strip()
        if resp.startswith('```'):
            resp = resp.lstrip('`').lstrip('json').lstrip('\n').strip()
            if resp.endswith('```'):
                resp = resp[:resp.rfind('```')].strip()
        return resp

    def _is_valid_waypoint(self, waypoint: str) -> bool:
        """Check if a waypoint string is a valid location (not a generic type)"""
        if not waypoint or not isinstance(waypoint, str):
            return False

        waypoint_lower = waypoint.lower().strip()

        # Check if it's a coordinate pair (lat,lng)
        if ',' in waypoint_lower:
            parts = waypoint_lower.split(',')
            if len(parts) == 2:
                try:
                    lat = float(parts[0].strip())
                    lng = float(parts[1].strip())
                    return (-90 <= lat <= 90) and (-180 <= lng <= 180)
                except ValueError:
                    pass

        # Check if it's a place_id (usually starts with ChIJ or similar)
        if waypoint.startswith(('ChIJ', 'EhIJ', 'CmRa', 'EjRy')):
            return True

        # Check if it's a generic place type (these should be filtered out)
        generic_types = [
            'gas station', 'grocery store', 'restaurant', 'coffee shop', 'cafe',
            'pharmacy', 'bank', 'atm', 'hospital', 'hotel', 'lodging',
            'shopping mall', 'mall', 'convenience store', 'car repair',
            'car wash', 'airport', 'train station', 'bus station', 'parking',
            'park', 'gym', 'beauty salon', 'clothing store', 'electronics store',
            'hardware store', 'book store', 'movie theater', 'bar', 'church',
            'school', 'library', 'post office', 'police', 'fire station'
        ]

        for generic_type in generic_types:
            if generic_type in waypoint_lower:
                return False

        # If it looks like an address or specific place name, consider it valid
        address_indicators = ['st', 'street', 'ave', 'avenue', 'rd', 'road', 'blvd', 'boulevard',
                              'lane', 'ln', 'drive', 'dr', 'way', 'plaza', 'pkwy', 'parkway']

        # Contains numbers (likely an address)
        if any(char.isdigit() for char in waypoint):
            return True

        # Contains address indicators
        waypoint_words = waypoint_lower.split()
        if any(indicator in waypoint_words for indicator in address_indicators):
            return True

        # If it's a specific business name and isn't too generic, consider it valid
        if len(waypoint) > 5 and waypoint != waypoint_lower:
            return True

        return False

    def _validate_place_data(self, place: Dict) -> bool:
        """Validate that place data has required fields for waypoint creation"""
        if not place:
            return False

        # Check for place_id
        if place.get("place_id"):
            return True

        # Check for valid coordinates
        geometry = place.get("geometry", {})
        location = geometry.get("location", {})

        if location.get("lat") is not None and location.get("lng") is not None:
            lat = location["lat"]
            lng = location["lng"]
            # Validate lat/lng are numbers and in valid ranges
            try:
                lat_float = float(lat)
                lng_float = float(lng)
                return (-90 <= lat_float <= 90) and (-180 <= lng_float <= 180)
            except (ValueError, TypeError):
                return False

        return False

    async def extract_waypoint_requirements(self, prompt: str, unmapped_details: List[str]) -> List[WaypointRequirement]:
        """Extract waypoint requirements using ChatGPT"""
        combined_text = f"Original prompt: {prompt}\nUnmapped details: {' '.join(unmapped_details)}"

        excluded_waypoints = '\n'.join([x for x in unmapped_details])

        system_prompt = """
        Extract waypoint requirements from routing text. Look for places the user wants to stop.

        Return a JSON array of waypoint objects with:
        - place_type: Generic type like "gas station", "grocery store", "restaurant"
        - direction: "there" (on way to destination), "back" (return trip), or "both"
        - specifics: Brand names, preferences like "walmart", "shell", "cheap gas", "drive-thru"
        - priority: 1=required stop, 2=preferred, 3=optional if convenient

        Examples:
        "stop for gas on the way there" -> {"place_type": "gas station", "direction": "there", "specifics": "", "priority": 1}
        "grab groceries at walmart on way home" -> {"place_type": "grocery store", "direction": "back", "specifics": "walmart", "priority": 1}
        "coffee would be nice" -> {"place_type": "coffee shop", "direction": "there", "specifics": "", "priority": 3}

        Preferred roads, bridges, or specific routes should NOT be included as waypoints.
        Here are route preferences the user specified (if any) to show you what to ignore:"""

        system_prompt += f"""\n
        {excluded_waypoints}

        Return empty array [] if no waypoints needed.
        """

        response = await self._open_ai_client.chat.completions.create(
            model=GPTModel.GPT_4_1_MINI,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": combined_text}
            ],
            temperature=0.1
        )

        try:
            content = self._strip_json_code_block(response.choices[0].message.content)
            waypoint_data = json.loads(content)
            return [WaypointRequirement(**req) for req in waypoint_data]
        except Exception as e:
            print(f"Failed to parse waypoint requirements: {e}")
            return []

    async def resolve_waypoints(self, waypoint_requirements: List[WaypointRequirement],
                                origin: str, destination: str):
        """Resolve generic waypoint requirements to specific places"""

        for requirement in waypoint_requirements:
            try:
                # Find places along the route
                places = await self._find_places_along_route(
                    requirement, origin, destination
                )
                logger.info(f"Found {len(places)} places for {requirement.place_type}")

                if places:
                    # Use ChatGPT to select the best place based on specifics
                    selected_place = await self._select_best_place(requirement, places)
                    requirement.resolved_place = selected_place
                    logger.info(f"Selected place: {selected_place.get('name', 'Unknown')} for {requirement.place_type}")
                else:
                    logger.warning(f"No places found for {requirement.place_type}")

            except Exception as e:
                logger.error(f"Failed to resolve waypoint {requirement.place_type}: {e}")

    async def _find_places_along_route(self, requirement: WaypointRequirement,
                                       origin: str, destination: str) -> List[Dict]:
        """Find places of the required type along the route"""

        try:
            # Get a rough route first to find midpoint for search
            temp_directions = await self._route_data_client.get_directions({
                "origin": origin,
                "destination": destination,
                "key": self._route_data_client._config.api_key
            })

            if not temp_directions.routes:
                logger.warning("No routes found for place search")
                return []

            # Find search location based on direction
            route = temp_directions.routes[0]
            leg = route.legs[0]

            if requirement.direction == "there":
                search_location = self._get_point_along_route(leg, 0.33)
            elif requirement.direction == "back":
                search_location = self._get_point_along_route(leg, 0.67)
            else:  # both
                search_location = self._get_point_along_route(leg, 0.5)

            logger.info(f"Search location for {requirement.place_type}: {search_location}")

            # Convert natural language place type to Google Places API type
            google_place_type = await self._convert_to_google_place_type(requirement.place_type)
            logger.info(f"Converted '{requirement.place_type}' to Google type: '{google_place_type}'")

            # Search for places using Google Places API
            places = await self._places_client.nearby_search(
                location=search_location,
                place_type=google_place_type,
                radius=5000,  # 5km radius
                keyword=requirement.specifics if requirement.specifics else None
            )

            return places[:5]  # Return top 5 candidates

        except Exception as e:
            logger.error(f"Error in _find_places_along_route: {e}")
            return []

    def _get_point_along_route(self, leg: Dict, fraction: float) -> str:
        """Get a point at given fraction along the route leg"""
        steps = leg.steps
        if not steps:
            return f"{leg.start_location.lat},{leg.start_location.lng}"

        total_distance = leg.distance.value
        target_distance = total_distance * fraction
        current_distance = 0

        for step in steps:
            step_distance = step.distance.value
            if current_distance + step_distance >= target_distance:
                # Found the step containing our target point
                step_fraction = (target_distance - current_distance) / step_distance
                start_lat = step.start_location.lat
                start_lng = step.start_location.lng
                end_lat = step.end_location.lat
                end_lng = step.end_location.lng

                # Simple linear interpolation
                target_lat = start_lat + (end_lat - start_lat) * step_fraction
                target_lng = start_lng + (end_lng - start_lng) * step_fraction

                return f"{target_lat},{target_lng}"

            current_distance += step_distance

        # Fallback to end location
        return f"{leg.end_location.lat},{leg.end_location.lng}"

    async def _convert_to_google_place_type(self, natural_language_type: str) -> str:
        """Convert natural language place type to Google Places API type using ChatGPT"""
        system_prompt = """
        Convert natural language place types to Google Places API types.
        
        Common Google Places API types include:
        - gas_station, grocery_or_supermarket, restaurant, cafe, pharmacy, bank, atm
        - hospital, lodging, shopping_mall, convenience_store, car_repair, car_wash
        - airport, train_station, bus_station, parking, tourist_attraction, park, gym
        - beauty_salon, hair_care, clothing_store, electronics_store, hardware_store
        - book_store, movie_theater, night_club, bar, liquor_store, church, school
        - university, library, post_office, police, fire_station, courthouse, city_hall
        
        Return the single best Google Places API type that matches the input.
        If unsure, return the closest match or use "establishment" as fallback.
        
        Examples:
        "gas station" -> "gas_station"
        "grocery store" -> "grocery_or_supermarket"
        "coffee shop" -> "cafe"
        "fast food" -> "restaurant"
        """

        response = await self._open_ai_client.chat.completions.create(
            model=GPTModel.GPT_4O_MINI,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Convert: {natural_language_type}"}
            ],
            temperature=0.1
        )

        try:
            google_type = response.choices[0].message.content.strip()
            if len(google_type.split()) > 1 or not google_type.replace('_', '').isalpha():
                return "establishment"
            return google_type
        except Exception as e:
            print(f"Failed to convert place type '{natural_language_type}': {e}")
            return "establishment"

    async def _select_best_place(self, requirement: WaypointRequirement, places: List[Dict]) -> Dict:
        """Use ChatGPT to select the best place based on user specifics"""
        if len(places) == 1:
            return places[0]

        places_summary = []
        for place in places:
            summary = {
                "name": place.get("name", ""),
                "rating": place.get("rating", 0),
                "price_level": place.get("price_level", 0),
                "vicinity": place.get("vicinity", ""),
                "types": place.get("types", [])
            }
            places_summary.append(summary)

        system_prompt = f"""
        Select the best place for this requirement:
        Place type: {requirement.place_type}
        User specifics: {requirement.specifics}
        Priority: {requirement.priority} (1=required, 2=preferred, 3=optional)
        
        Consider:
        - Brand preferences in specifics
        - Rating and reviews
        - Price level if mentioned (cheap, expensive)
        - Location convenience
        
        Return the index (0-based) of the best place.
        """

        response = await self._open_ai_client.chat.completions.create(
            model=GPTModel.GPT_4_1_MINI,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Places: {json.dumps(places_summary)}"}
            ],
            temperature=0.1
        )

        try:
            index = int(response.choices[0].message.content.strip())
            return places[index] if 0 <= index < len(places) else places[0]
        except:
            return places[0]

    def insert_waypoints_into_model(self, model_data: Dict, waypoint_requirements: List[WaypointRequirement]) -> Dict:
        """Insert resolved waypoints into the directions model"""

        # Start with existing valid waypoints, filtering out generic place types
        existing_waypoints = model_data.get("waypoints", [])
        if existing_waypoints is None:
            existing_waypoints = []
        valid_existing_waypoints = [wp for wp in existing_waypoints if self._is_valid_waypoint(wp)]

        logger.info(f"Original waypoints: {existing_waypoints}")
        logger.info(f"Valid existing waypoints after filtering: {valid_existing_waypoints}")

        # Start fresh with only valid existing waypoints
        waypoints = valid_existing_waypoints.copy()

        valid_waypoints_added = 0
        for requirement in waypoint_requirements:
            if requirement.resolved_place and self._validate_place_data(requirement.resolved_place):
                place = requirement.resolved_place
                waypoint = None

                # Prefer coordinates over place_id for reliability
                if place.get("geometry", {}).get("location"):
                    loc = place["geometry"]["location"]
                    try:
                        lat = float(loc["lat"])
                        lng = float(loc["lng"])
                        waypoint = f"{lat},{lng}"
                        logger.info(f"Added coordinate waypoint: {waypoint} for {requirement.place_type}")
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Invalid coordinates for {requirement.place_type}: {e}")

                # Fallback to place_id if coordinates failed
                if not waypoint and place.get("place_id"):
                    waypoint = place["place_id"]
                    logger.info(f"Added place_id waypoint: {waypoint} for {requirement.place_type}")

                if waypoint:
                    waypoints.append(waypoint)
                    valid_waypoints_added += 1
                else:
                    logger.warning(f"Could not create waypoint for {requirement.place_type}")
            else:
                logger.warning(f"Invalid or missing place data for {requirement.place_type}")

        # Limit waypoints to avoid API limits (Google allows up to 25)
        if len(waypoints) > 20:
            logger.warning(f"Too many waypoints ({len(waypoints)}), limiting to 20")
            waypoints = waypoints[:20]

        model_data["waypoints"] = waypoints
        logger.info(f"Final waypoints: {waypoints} (kept {len(valid_existing_waypoints)} existing, added {valid_waypoints_added} new)")
        return model_data
