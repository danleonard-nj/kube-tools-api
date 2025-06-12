import requests
import json
import time
import openai
from typing import Dict, List
from clients.google_places_client import GooglePlacesClient
from domain.gpt import GPTModel
from models.googe_maps_models import DirectionsRequestModel, GooglePlaceDetails
from framework.logger import get_logger

logger = get_logger(__name__)


GOOGLE_API_KEY = 'AIzaSyBkrdQRC2SvrHI1ho3DTRoH7MWNO8S1jmM'


class RouteParserHelper:
    """Handles parsing of natural language prompts into structured route requests"""

    def __init__(self, openai_client: openai.AsyncOpenAI, places_client: GooglePlacesClient):
        self._open_ai_client = openai_client
        self._places_client = places_client

    def _strip_json_code_block(self, response: str) -> str:
        """Helper to remove code block markers (```json ... ```) from a response string."""
        resp = response.strip()
        if resp.startswith('```'):
            # Remove leading code block markers
            resp = resp.lstrip('`').lstrip('json').lstrip('\n').strip()
            # Remove any trailing code block
            if resp.endswith('```'):
                resp = resp[:resp.rfind('```')].strip()
        return resp

    def _fix_departure_time(self, model_data: Dict) -> Dict:
        """Fix departure_time if it's in the past or invalid"""

        departure_time = model_data.get("departure_time")
        if not departure_time:
            return model_data

        current_timestamp = int(time.time())

        # Handle string values
        if isinstance(departure_time, str):
            if departure_time.lower() == "now":
                model_data["departure_time"] = "now"
                logger.info("Departure time set to 'now'")
                return model_data
            else:
                # Try to parse as timestamp
                try:
                    departure_timestamp = int(departure_time)
                    departure_time = departure_timestamp
                except ValueError:
                    logger.warning(f"Invalid departure_time string: {departure_time}, removing it")
                    del model_data["departure_time"]
                    return model_data

        # Handle numeric values
        if isinstance(departure_time, (int, float)):
            departure_timestamp = int(departure_time)

            # Check if it's in the past (add 60 second buffer)
            if departure_timestamp < (current_timestamp - 60):
                logger.warning(f"Departure time {departure_timestamp} is in the past (current: {current_timestamp}), setting to 'now'")
                model_data["departure_time"] = "now"
            else:
                logger.info(f"Departure time {departure_timestamp} is valid")
                model_data["departure_time"] = departure_timestamp

        return model_data

    async def _normalize_address(self, address: str) -> GooglePlaceDetails:
        """
        Normalize an address using Google Places text search and details lookup. Returns full place details.
        Raises Exception if no result is found.
        """
        results = await self._places_client.text_search(query=address)
        if not results:
            raise Exception(f"Could not normalize address: '{address}'. No results from Google Places.")
        first_result = results[0] if results else None
        if not first_result or not first_result.place_id:
            raise Exception(f"No place_id found for address: '{address}'")
        # Fetch full details to get address_components
        details = await self._places_client.get_place_details(place_id=first_result.place_id)
        if not details:
            raise Exception(f"Could not fetch place details for place_id: {first_result.place_id}")
        return details

    async def parse_prompt_to_directions_request(self, prompt: str) -> Dict:
        """
        Uses ChatGPT to parse a natural language prompt into a DirectionsRequestModel and a CustomDimensions model.
        Returns {"model": DirectionsRequestModel, "custom_dimensions": CustomDimensions}
        """

        # Provide the full DirectionsRequestModel schema and types for ChatGPT
        model_schema = {
            "origin": "string (required) - address, latlng, or place_id",
            "destination": "string (required) - address, latlng, or place_id",
            "mode": "string (optional) - one of: driving, walking, bicycling, transit",
            "waypoints": "list of strings (optional)",
            "alternatives": "bool (optional)",
            "avoid": "list of strings (optional) - any of: tolls, highways, ferries, indoor",
            "language": "string (optional) - e.g. 'en', 'fr'",
            "units": "string (optional) - 'metric' or 'imperial'",
            "region": "string (optional) - ccTLD, e.g. 'us', 'uk'",
            "departure_time": "string or int (optional) - 'now' or unix timestamp",
            "arrival_time": "int (optional) - unix timestamp (transit only)",
            "transit_mode": "list of strings (optional) - any of: bus, subway, train, tram, rail",
            "transit_routing_preference": "string (optional) - 'less_walking' or 'fewer_transfers'",
            "traffic_model": "string (optional) - 'best_guess', 'pessimistic', 'optimistic' (driving only)",
            "optimize_waypoints": "bool (optional)",
            "custom": "dict (optional) - any extra params"
        }
        schema_str = json.dumps(model_schema, indent=2)

        example = {
            "model": {
                "origin": "38 Farmhouse Lane, Voorhees, NJ",
                "destination": "23 Pippins Way, Morristown",
                "mode": "driving",
                "waypoints": ["gas station", "Walmart"],
                "avoid": ["tolls", "ferries"],
                "departure_time": "now",
                "traffic_model": "best_guess"
            },
            "unmapped_details": {
                "route_prefs": ["use the turnpike", "avoid farm roads"],
                "place_requests": ["gas station", "Walmart"],
            }
        }
        example_str = json.dumps(example, indent=2)

        system_prompt = (
            "You are an assistant that extracts structured route request data from user prompts.\n"
            "Given a user prompt, return a JSON object with as many fields as possible mapped to the DirectionsRequestModel.\n"
            "\nHere is the schema for DirectionsRequestModel (field: type/description):\n"
            + schema_str +
            "\nAlso return a list of any details from the prompt that could not be mapped, in an unmapped_details section.\n"
            "\nIMPORTANT RULES:\n"
            "- If the user specifies they want to take or avoid specific roads, highways, or bridges (e.g., 'take the turnpike', 'avoid farm roads'), include these preferences in the waypoints array if they describe an explicit path or route to take. Otherwise, also add them to unmapped_details.route_prefs.\n"
            "- If the user requests generic places to stop (e.g., 'stop at a gas station', 'grocery store'), add these to unmapped_details.place_requests unless the user specifies them as required stops, in which case include them as waypoints.\n"
            "- If a location is ambiguous (such as 'Brace Road'), and the user does not specify it as a stop, treat it as a route preference: add it to unmapped_details.preferred_routes and (if it represents a road/route to travel along) include it as a waypoint.\n"
            "- For departure_time, use 'now' only if the user indicates immediate departure; otherwise omit this field if not specified.\n"
            "- Ensure to include any preferred routes that are waypoints in both sections, preferred routes must exist in both.\n"
            "- When in doubt, prioritize including explicit route preferences (e.g., specific roads to take) in the waypoints array. Record any additional preferences in unmapped_details.route_prefs for clarity.\n"
            "- Sample prompt: take me to 23 pippins way Morristown from 38 farmhouse lane voorhees nj, use the turnpike and avoid farm roads, have to make a pit stop at a gas station and a Walmart and leaving at 6pm\n"
            "Example output:\n"
            + example_str
        )

        user_prompt = f"Prompt: {prompt}\nReturn JSON as described."

        # Use the OpenAI client directly
        completion = await self._open_ai_client.chat.completions.create(
            model=GPTModel.GPT_4_1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0
        )
        response = completion.choices[0].message.content
        response = self._strip_json_code_block(response)

        try:
            data = json.loads(response)
            model_data = data.get("model", {})
            custom_dimensions_raw = data.get("unmapped_details", {})
            from models.googe_maps_models import CustomDimensions
            if not isinstance(custom_dimensions_raw, CustomDimensions):
                custom_dimensions = CustomDimensions(**custom_dimensions_raw) if isinstance(custom_dimensions_raw, dict) else CustomDimensions()
            else:
                custom_dimensions = custom_dimensions_raw

            # Filter avoid list for valid values and move invalids to custom_dimensions.other
            valid_avoid = {"tolls", "highways", "ferries", "indoor"}
            avoid = model_data.get("avoid", [])
            if isinstance(avoid, list):
                filtered_avoid = []
                for item in avoid:
                    if item in valid_avoid:
                        filtered_avoid.append(item)
                    else:
                        custom_dimensions.other.append(f"avoid: {item} (invalid, not supported)")
                model_data["avoid"] = filtered_avoid

            # Fix departure_time if it's in the past or invalid
            model_data = self._fix_departure_time(model_data)
            model = DirectionsRequestModel.model_validate(model_data)
            # Use preferred_routes from custom_dimensions
            preferred_routes = custom_dimensions.preferred_routes if hasattr(custom_dimensions, 'preferred_routes') else []

            origin = await self._normalize_address(model.origin)
            destination = await self._normalize_address(model.destination)

            origin_city = ''
            origin_state = ''
            for component in origin.address_components:
                if 'locality' in component.types:
                    origin_city = component.long_name
                if 'administrative_area_level_1' in component.types:
                    origin_state = component.short_name
                if origin_city and origin_state:
                    break

            model.origin = origin.formatted_address
            model.destination = destination.formatted_address

            all_waypoint_options = []  # List of lists: each sublist contains all candidate points for a waypoint
            if model.waypoints:
                for i, waypoint in enumerate(model.waypoints):
                    if waypoint in preferred_routes:
                        # Get all candidate points for this waypoint
                        candidate_points = await self.get_road_sample_points(
                            waypoint, origin_city, origin_state
                        )
                        # Convert to 'lat,lng' strings if needed
                        candidate_points_str = []
                        for pt in candidate_points:
                            if hasattr(pt, 'geometry') and hasattr(pt.geometry, 'location'):
                                lat, lng = pt.geometry.location.lat, pt.geometry.location.lng
                                candidate_points_str.append(f"{lat},{lng}")
                            elif isinstance(pt, tuple) and len(pt) == 2:
                                candidate_points_str.append(f"{pt[0]},{pt[1]}")
                            else:
                                candidate_points_str.append(str(pt))
                        all_waypoint_options.append(candidate_points_str)
                        # For legacy compatibility, still set the first as the default
                        if candidate_points_str:
                            model.waypoints[i] = candidate_points_str[0]
                    else:
                        all_waypoint_options.append([model.waypoints[i]])
        except Exception as e:
            model = None
            custom_dimensions = CustomDimensions(other=[f"Error parsing ChatGPT response: {e}", str(response)])
            raise

        return dict(model=model.model_dump(), unwrapped_details=custom_dimensions.model_dump(), all_waypoint_options=all_waypoint_options)

    async def geocode_address(self, address):

        return await self._places_client.geocode_address(address)

    async def get_road_sample_points(self, road_name, city, state, num_points=5):
        # We'll query addresses like "100 Brace Rd", "500 Brace Rd", etc.
        # This is a hacky way if you can't get real geometry
        points = []
        for n in range(100, 1000, int(900/num_points)):
            addr = f"{n} {road_name}, {city}, {state}"
            loc = await self.geocode_address(addr)
            if loc:
                points.append(loc)
        return points

    def closest_point_to_origin(self, origin, dest, points):
        # Optionally factor in direction to dest for smarter selection
        def score(pt):
            return ((pt[0] - origin[0])**2 + (pt[1] - origin[1])**2)
        return min(points, key=score)

    def _geographic_midpoint(self, coord1, coord2):
        """Compute the geographic midpoint between two (lat, lng) tuples."""
        from math import radians, degrees, sin, cos, atan2
        lat1, lon1 = radians(coord1[0]), radians(coord1[1])
        lat2, lon2 = radians(coord2[0]), radians(coord2[1])
        dlon = lon2 - lon1
        bx = cos(lat2) * cos(dlon)
        by = cos(lat2) * sin(dlon)
        lat3 = atan2(
            sin(lat1) + sin(lat2),
            ((cos(lat1) + bx) ** 2 + by ** 2) ** 0.5
        )
        lon3 = lon1 + atan2(by, cos(lat1) + bx)
        return (degrees(lat3), degrees(lon3))

    def _euclidean_distance(self, pt1, pt2):
        return ((pt1[0] - pt2[0]) ** 2 + (pt1[1] - pt2[1]) ** 2) ** 0.5

    def _best_waypoint_by_scenarios(self, origin, dest, points):
        """
        Evaluate each candidate point by its distance to origin, destination, and midpoint.
        Returns the point with the minimum distance to any of these scenarios.
        """
        midpoint = self._geographic_midpoint(origin, dest)
        best_point = None
        best_score = float('inf')
        for pt in points:
            # pt can be a GooglePlaceDetails or tuple
            if hasattr(pt, 'geometry') and hasattr(pt.geometry, 'location'):
                lat, lng = pt.geometry.location.lat, pt.geometry.location.lng
                pt_tuple = (lat, lng)
            elif isinstance(pt, tuple) and len(pt) == 2:
                pt_tuple = pt
            else:
                continue
            score = min(
                self._euclidean_distance(pt_tuple, origin),
                self._euclidean_distance(pt_tuple, dest),
                self._euclidean_distance(pt_tuple, midpoint)
            )
            if score < best_score:
                best_score = score
                best_point = pt_tuple
        return best_point

    async def pick_best_road_waypoint(self, origin_addr, dest_addr, road_name, city, state):
        origin = await self.geocode_address(origin_addr)
        dest = await self.geocode_address(dest_addr)
        if not (origin and dest):
            raise Exception("Could not geocode origin/destination")
        # Convert to (lat, lng) tuples

        def to_latlng(place):
            if hasattr(place, 'geometry') and hasattr(place.geometry, 'location'):
                return (place.geometry.location.lat, place.geometry.location.lng)
            elif isinstance(place, tuple) and len(place) == 2:
                return place
            return None
        origin_pt = to_latlng(origin)
        dest_pt = to_latlng(dest)
        points = await self.get_road_sample_points(road_name, city, state)
        if not points:
            raise Exception("Could not find road points")
        # Use new scenario-based selection
        return self._best_waypoint_by_scenarios(origin_pt, dest_pt, points)
