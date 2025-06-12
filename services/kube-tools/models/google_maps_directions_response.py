from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class DirectionsResponseGeocodedWaypoint(BaseModel):
    geocoder_status: str
    place_id: str
    types: List[str]
    partial_match: Optional[bool] = None


class DirectionsResponseLocation(BaseModel):
    lat: float
    lng: float


class DirectionsResponseDistance(BaseModel):
    text: str
    value: int


class DirectionsResponseDuration(BaseModel):
    text: str
    value: int


class DirectionsResponseStep(BaseModel):
    distance: DirectionsResponseDistance
    duration: DirectionsResponseDuration
    end_location: DirectionsResponseLocation
    html_instructions: str
    polyline: Dict[str, str]
    start_location: DirectionsResponseLocation
    travel_mode: str
    maneuver: Optional[str] = None


class DirectionsResponseLeg(BaseModel):
    steps: List[DirectionsResponseStep]
    distance: DirectionsResponseDistance
    duration: DirectionsResponseDuration
    end_address: str
    end_location: DirectionsResponseLocation
    start_address: str
    start_location: DirectionsResponseLocation
    traffic_speed_entry: List[Any]
    via_waypoint: List[Any]


class DirectionsResponseBounds(BaseModel):
    northeast: DirectionsResponseLocation
    southwest: DirectionsResponseLocation


class DirectionsResponsePolyline(BaseModel):
    points: str


class DirectionsResponseRoute(BaseModel):
    bounds: DirectionsResponseBounds
    copyrights: str
    legs: List[DirectionsResponseLeg]
    overview_polyline: DirectionsResponsePolyline
    summary: str
    warnings: List[str]
    waypoint_order: List[int]
    fare: Optional[Dict[str, Any]] = None


class DirectionsResponseModel(BaseModel):
    geocoded_waypoints: List[DirectionsResponseGeocodedWaypoint]
    routes: List[DirectionsResponseRoute]
    status: str
