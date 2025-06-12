import json
import openai
from typing import Dict, List

from pydantic import BaseModel
from sympy import content
from domain.gpt import GPTModel
from services.route_engine.waypoint_resolver import WaypointRequirement
from framework.logger import get_logger

logger = get_logger(__name__)


class BestRouteSelection(BaseModel):
    index: int
    summary: str


class RouteSelectorHelper:
    """Handles route selection logic using LLM analysis"""

    def __init__(self, openai_client: openai.AsyncOpenAI):
        self._open_ai_client = openai_client

    def _calculate_highway_percentage(self, steps) -> float:
        """Calculate percentage of route that uses highways"""
        if not steps:
            return 0.0
        highway_distance = 0
        total_distance = 0
        for step in steps:
            dist = step.distance.value
            total_distance += dist
            instructions = (step.html_instructions or '').lower()
            if any(word in instructions for word in ["highway", "freeway", "interstate", "i-", "hwy"]):
                highway_distance += dist
        return highway_distance / total_distance if total_distance > 0 else 0.0

    def _extract_waypoints(self, steps) -> List[str]:
        """Extract waypoint names from route steps"""
        waypoints = []
        for step in steps:
            instructions = (step.html_instructions or '')
            if "toward" in instructions.lower():
                parts = instructions.lower().split("toward")
                if len(parts) > 1:
                    waypoint = parts[1].strip().split()[0]
                    if waypoint and waypoint not in waypoints:
                        waypoints.append(waypoint)
        return waypoints[:3]

    def analyze_route_options(self, directions_response) -> List:
        """Analyze route options and return structured data (prefer models, not dicts)"""

        options = []
        # Accept both a list of routes or an object with .routes
        if isinstance(directions_response, list):
            routes = directions_response
        elif hasattr(directions_response, "routes"):
            routes = directions_response.routes
        elif isinstance(directions_response, dict) and "routes" in directions_response:
            routes = directions_response["routes"]
        else:
            logger.warning(f"Could not extract routes from directions_response: {directions_response}")
            routes = []

        for idx, route in enumerate(routes):
            leg = route.legs[0]
            logger.info(f"Processing route {idx}: summary={route.summary}, leg={leg}")

            # Instead of dumping to dict, just pass the model object
            option = route
            options.append(option)

        logger.info(f"Returning {len(options)} route options (as models)")
        return options

    async def select_best_route_with_llm(self, route_options: List[Dict],
                                         original_prompt: str,
                                         waypoint_requirements: List[WaypointRequirement]) -> BestRouteSelection:
        """Use ChatGPT to select the best route considering waypoints and user preferences"""
        # if len(route_options) == 1:
        #     return BestRouteSelection(
        #         route_options[0]

        # Summarize routes for LLM with detailed info
        route_summaries = []
        for i, route in enumerate(route_options):
            summary = route.get('summary', '')
            distance_km = route.get('distance_km', 0)
            duration_minutes = route.get('duration_minutes', 0)
            has_tolls = route.get('has_tolls', False)
            highway_percentage = route.get('highway_percentage', 0.0)
            # Collect all steps from all legs
            steps = []
            legs = route.get('legs', [])
            for leg in legs:
                leg_steps = leg.get('steps', []) if isinstance(leg, dict) else getattr(leg, 'steps', [])
                steps.extend(leg_steps)
            # Build step-by-step summary (all steps, robust to object or dict)
            step_summaries = []
            for step in steps:
                if isinstance(step, dict):
                    instruction = step.get('html_instructions') or step.get('instruction') or ''
                    road = step.get('road_name') or ''
                    dist = step.get('distance', {}).get('text') or ''
                    dur = step.get('duration', {}).get('text') or ''
                    maneuver = step.get('maneuver', '')
                else:
                    instruction = getattr(step, 'html_instructions', None) or getattr(step, 'instruction', '') or ''
                    road = getattr(step, 'road_name', '') or ''
                    dist = getattr(getattr(step, 'distance', None), 'text', '') or ''
                    dur = getattr(getattr(step, 'duration', None), 'text', '') or ''
                    maneuver = getattr(step, 'maneuver', '')
                step_summaries.append(f"- {instruction} {f'on {road}' if road else ''} ({dist}, {dur}) {f'[{maneuver}]' if maneuver else ''}")
            steps_text = '\n'.join(step_summaries) if step_summaries else 'No steps available.'
            # Notable waypoints/landmarks
            waypoints = route.get('waypoints', [])
            if waypoints:
                # Fix: waypoints may be a list of strings (lat,lng or place_id), not dicts
                waypoints_text = ', '.join([w.get('name', str(w)) if hasattr(w, 'get') else str(w) for w in waypoints])
            else:
                waypoints_text = 'None'
            # Any special metadata
            scenic = route.get('scenic', False)
            traffic = route.get('traffic', '')
            restrictions = route.get('restrictions', '')
            summary_str = f"""Route {i+1}: {summary}\n" \
                f"- Distance: {distance_km:.1f} km\n" \
                f"- Duration: {duration_minutes:.0f} minutes\n" \
                f"- Tolls: {'Yes' if has_tolls else 'No'}\n" \
                f"- Highway: {highway_percentage*100:.0f}%\n" \
                f"- Waypoints/Landmarks: {waypoints_text}\n" \
                f"- Scenic: {'Yes' if scenic else 'No'}\n" \
                f"- Traffic: {traffic if traffic else 'N/A'}\n" \
                f"- Restrictions: {restrictions if restrictions else 'N/A'}\n" \
                f"- Steps (all):\n{steps_text}"""
            route_summaries.append(summary_str)

        # Summarize waypoint resolution status
        waypoint_summary = []
        for req in waypoint_requirements:
            if req.resolved_place:
                waypoint_summary.append(f"✓ {req.place_type} resolved: {req.resolved_place.get('name', 'Unknown')}")
            else:
                waypoint_summary.append(f"✗ {req.place_type} not found")

        prompt = f"""
        Select the best route for this request: "{original_prompt}"

        Waypoints: {' | '.join(waypoint_summary)}

        Routes:
        {chr(10).join(route_summaries)}

        Consider the user's original request and preferences.
        Return a JSON object with two fields:
        - 'index': the route number (1-{len(route_options)}),
        - 'summary': one sentence explaining why this route best fits the user's preferences.
        Example response: {{"index": 2, "summary": "This route avoids highways and has the shortest travel time."}}
        """

        response = await self._open_ai_client.chat.completions.create(
            model=GPTModel.GPT_4_1,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an assistant that selects the best route for the user based on their request and preferences. "
                        "When comparing routes, strongly prefer routes that are not excessively long and avoid routes with waypoints that are far off the direct path or seem inaccurate. "
                        "Penalize routes with much greater distance or with waypoints that do not make sense geographically. "
                        "Return your answer as a JSON object in the format: "
                        '{"index": <route_number>, "summary": "<one sentence reason>"}'
                    )
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )

        content = response.choices[0].message.content.strip()

        data = json.loads(content)
        return BestRouteSelection.model_validate(data)

        # try:
        #     route_num = int(content)
        #     return route_options[route_num - 1] if 1 <= route_num <= len(route_options) else route_options[0]
        # except:
        #     return route_options[0]  # Fallback to first route
