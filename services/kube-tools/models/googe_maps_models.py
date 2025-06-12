from dataclasses import dataclass
from typing import List, Literal, Optional, Union
from pydantic import BaseModel, Field

AddressComponentType = Literal[
    "street_number", "route", "intersection", "political", "country",
    "administrative_area_level_1", "administrative_area_level_2", "administrative_area_level_3",
    "administrative_area_level_4", "administrative_area_level_5", "colloquial_area", "locality",
    "sublocality", "sublocality_level_1", "sublocality_level_2", "sublocality_level_3",
    "sublocality_level_4", "sublocality_level_5", "neighborhood", "premise", "subpremise",
    "postal_code", "postal_code_suffix", "natural_feature", "airport", "park", "point_of_interest", "floor",
    "establishment", "parking", "post_box", "postal_town", "room", "street_address",
    "bus_station", "train_station", "transit_station"
]


class GoogleMapsConfig(BaseModel):
    api_key: str
    base_url: str = "https://maps.googleapis.com/maps/api"


class GoogleMapsConfigModel(BaseModel):
    """Pydantic model for Google Maps API configuration"""
    api_key: str
    base_url: str = "https://maps.googleapis.com/maps/api"


class RouteOptionModel(BaseModel):
    """Pydantic model for a single route option with metadata"""
    route_data: dict
    summary: str
    distance_km: float
    duration_minutes: int
    has_tolls: bool = False
    highway_percentage: float = 0.0
    via_waypoints: list[str] = Field(default_factory=list)


class Waypoint(BaseModel):
    location: str  # Can be "lat,lng" or address or place_id (e.g. "place_id:ChIJ...")
    stopover: Optional[bool] = True  # Whether this waypoint is a stopover (vs a pass-through)


class DirectionsRequestModel(BaseModel):
    # --- REQUIRED ---
    origin: str  # address, latlng, or place_id
    destination: str  # address, latlng, or place_id

    # --- OPTIONAL ---
    mode: Optional[Literal["driving", "walking", "bicycling", "transit"]] = None
    waypoints: Optional[list[str]] = None  # as strings, or expand to List[Waypoint] for more control
    alternatives: Optional[bool] = True
    avoid: Optional[list[Literal[
        "tolls", "highways", "ferries", "indoor"
    ]]] = None
    language: Optional[str] = None  # e.g., "en", "fr"
    units: Optional[Literal["metric", "imperial"]] = None
    region: Optional[str] = None  # ccTLD ("us", "uk", etc)
    departure_time: Optional[Union[str, int]] = None  # "now" or unix timestamp
    arrival_time: Optional[int] = None  # unix timestamp (transit only)
    transit_mode: Optional[list[Literal[
        "bus", "subway", "train", "tram", "rail"
    ]]] = None  # transit only
    transit_routing_preference: Optional[Literal[
        "less_walking", "fewer_transfers"
    ]] = None  # transit only
    traffic_model: Optional[Literal[
        "best_guess", "pessimistic", "optimistic"
    ]] = None  # driving + departure_time only
    optimize_waypoints: Optional[bool] = None  # legacy, can include "optimize:true|" in waypoints
    # Deprecated/Legacy (not recommended for new apps)
    arrival_time: Optional[int] = None
    # API key should not be sent here in real code, for completeness:
    key: Optional[str] = None

    # Additional parameters as per docs (seldom used)
    # Provide full flexibility for any undocumented options
    custom: Optional[dict] = Field(default_factory=dict)

    class Config:
        schema_extra = {
            "example": {
                "origin": "Philadelphia,PA",
                "destination": "New York,NY",
                "mode": "driving",
                "waypoints": ["Princeton,NJ", "Newark,NJ"],
                "avoid": ["tolls", "ferries"],
                "departure_time": "now",
                "traffic_model": "best_guess"
            }
        }


@dataclass
class RouteOption:
    """Represents a single route option with metadata"""
    route_data: dict
    summary: str
    distance_km: float
    duration_minutes: int
    has_tolls: bool = False
    highway_percentage: float = 0.0
    via_waypoints: list[str] = None

    def __post_init__(self):
        if self.via_waypoints is None:
            self.via_waypoints = []


class AddressComponent(BaseModel):
    long_name: Optional[str] = None
    short_name: Optional[str] = None
    types: Optional[list[AddressComponentType]] = None


class GooglePlaceDetails(BaseModel):
    place_id: Optional[str] = None
    name: Optional[str] = None
    rating: Optional[float] = None
    price_level: Optional[int] = None
    formatted_address: Optional[str] = None
    geometry: Optional[dict] = None
    opening_hours: Optional[dict] = None
    photos: Optional[list] = None
    reviews: Optional[list] = None
    address_components: Optional[list[AddressComponent]] = None

    class Config:
        orm_mode = True


class CustomDimensions(BaseModel):
    preferred_routes: Optional[List[str]] = Field(default_factory=list)
    excluded_routes: Optional[List[str]] = Field(default_factory=list)
    route_prefs: Optional[List[str]] = Field(default_factory=list)
    place_requests: Optional[List[str]] = Field(default_factory=list)
    other: Optional[List[str]] = Field(default_factory=list)
    # Add any other fields you expect from the old unmapped_details
    # This model can be extended as needed
