import openrouteservice
import osmnx as ox
from shapely.geometry import LineString, Point
from shapely.ops import unary_union
import geojson

# ---------- CONFIG ----------

ORS_API_KEY = "5b3ce3597851110001cf6248bfa02a87ea5c4de484dabd8c9722abc5"  # <-- put your key here

# Example coordinates (lng, lat)
origin = (-75.006, 39.900)        # e.g. west Cherry Hill, NJ
destination = (-74.945, 39.910)   # e.g. east Cherry Hill, NJ

avoid_road = "Brace Road"
prefer_road = "Jefferson Road"

# ---------- HELPER FUNCTIONS ----------


def get_road_segments(edges, road_name):
    """Return all LineStrings for a named road."""
    def matches_name(name, target):
        if isinstance(name, list):
            return target in name
        if isinstance(name, str):
            return target.lower() in name.lower()
        return False
    return list(edges[edges['name'].apply(lambda n: matches_name(n, road_name))].geometry)


def best_waypoint_on_road(road_segments, origin, destination):
    """Pick the road point closest to the direct line from origin to destination."""
    ab_line = LineString([origin[::-1], destination[::-1]])  # shapely uses (lng, lat)
    min_dist = float('inf')
    best_point = None
    for seg in road_segments:
        # Project direct line onto the segment
        proj = seg.interpolate(seg.project(ab_line))
        dist = proj.distance(ab_line)
        if dist < min_dist:
            min_dist = dist
            best_point = proj
    if best_point:
        return (best_point.y, best_point.x)
    else:
        return None

# ---------- MAIN ----------


if __name__ == "__main__":
    # Calculate bounding box with padding
    lats, lngs = zip(origin, destination)
    buffer = 0.02
    north = max(lats) + buffer
    south = min(lats) - buffer
    east = max(lngs) + buffer
    west = min(lngs) - buffer

    # Download drivable graph and get all edges
    print("Downloading road network...")
    G = ox.graph_from_bbox(north, south, east, west, network_type='drive')
    edges = ox.graph_to_gdfs(G, nodes=False)

    # Get prefer road waypoint
    print(f"Locating '{prefer_road}' segments...")
    prefer_segments = get_road_segments(edges, prefer_road)
    prefer_point = best_waypoint_on_road(prefer_segments, origin, destination)
    if prefer_point:
        print(f"Preferred waypoint: {prefer_point}")
    else:
        print(f"No segments found for {prefer_road}")

    # Buffer and union avoid road
    print(f"Buffering '{avoid_road}' segments...")
    avoid_segments = get_road_segments(edges, avoid_road)
    buffers = [seg.buffer(0.0002) for seg in avoid_segments]  # ~20m buffer
    avoid_polygon = unary_union(buffers) if buffers else None

    # Build coordinate list
    coordinates = [origin]
    if prefer_point:
        coordinates.append(prefer_point)
    coordinates.append(destination)

    # Build ORS request
    print("Requesting route from OpenRouteService...")
    client = openrouteservice.Client(key=ORS_API_KEY)
    options = {}
    if avoid_polygon:
        feature = geojson.Feature(geometry=avoid_polygon)
        options["avoid_polygons"] = geojson.loads(geojson.dumps(feature["geometry"]))

    route = client.directions(
        coordinates,
        profile="driving-car",
        format="geojson",
        options=options
    )

    summary = route['features'][0]['properties']['summary']
    print("\nRoute summary:")
    print("Distance (km):", round(summary['distance']/1000, 2))
    print("Duration (min):", round(summary['duration']/60, 1))
    print("\nFirst 5 steps:")
    for step in route['features'][0]['properties']['segments'][0]['steps'][:5]:
        print("-", step['instruction'])
