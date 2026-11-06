"""Build a small attributed Hyderabad road GeoJSON and georeferenced TIFF sample.

Input is an OpenStreetMap API XML bounding-box extract. Requires Pillow only for
the optional rendered GeoTIFF; the routable road data remains in GeoJSON.
"""

from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, TiffImagePlugin


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "hyderabad_roads_sample.osm"
OUT = ROOT / "data"
BOUNDS = (78.350, 17.430, 78.380, 17.450)  # west, south, east, north
WIDTH, HEIGHT = 1200, 800


def clip_segment(a: tuple[float, float], b: tuple[float, float]):
    """Clip a lon/lat segment to BOUNDS using Liang-Barsky."""
    west, south, east, north = BOUNDS
    dx, dy = b[0] - a[0], b[1] - a[1]
    p = (-dx, dx, -dy, dy)
    q = (a[0] - west, east - a[0], a[1] - south, north - a[1])
    lo, hi = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return None
            continue
        ratio = qi / pi
        if pi < 0:
            lo = max(lo, ratio)
        else:
            hi = min(hi, ratio)
        if lo > hi:
            return None
    return ((a[0] + lo * dx, a[1] + lo * dy), (a[0] + hi * dx, a[1] + hi * dy))


def main() -> None:
    tree = ET.parse(SOURCE)
    root = tree.getroot()
    nodes = {node.attrib["id"]: (float(node.attrib["lon"]), float(node.attrib["lat"]))
             for node in root.findall("node")}
    features = []
    raster = Image.new("RGB", (WIDTH, HEIGHT), "#f7f5ef")
    draw = ImageDraw.Draw(raster)
    west, south, east, north = BOUNDS

    def pixel(point):
        lon, lat = point
        return ((lon - west) / (east - west) * (WIDTH - 1),
                (north - lat) / (north - south) * (HEIGHT - 1))

    for way in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        if "highway" not in tags:
            continue
        points = [nodes[nd.attrib["ref"]] for nd in way.findall("nd") if nd.attrib["ref"] in nodes]
        if len(points) < 2:
            continue
        clipped = []
        for a, b in zip(points, points[1:]):
            segment = clip_segment(a, b)
            if segment:
                if not clipped or clipped[-1] != segment[0]:
                    if len(clipped) > 1:
                        features.append((clipped, tags, way.attrib["id"]))
                    clipped = [segment[0]]
                clipped.append(segment[1])
            elif len(clipped) > 1:
                features.append((clipped, tags, way.attrib["id"]))
                clipped = []
        if len(clipped) > 1:
            features.append((clipped, tags, way.attrib["id"]))

    geo_features = []
    for points, tags, osm_id in features:
        road_class = tags.get("highway", "road")
        coords = [[round(lon, 8), round(lat, 8)] for lon, lat in points]
        geo_features.append({
            "type": "Feature", "id": f"way/{osm_id}",
            "properties": {"highway": road_class, "name": tags.get("name"), "osm_id": osm_id},
            "geometry": {"type": "LineString", "coordinates": coords},
        })
        width = 4 if road_class in {"primary", "trunk", "secondary", "tertiary"} else 2
        draw.line([pixel(point) for point in points], fill="#87939a" if width == 4 else "#b2b9bb", width=width)

    geojson = {"type": "FeatureCollection", "name": "Hyderabad OSM road sample",
               "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
               "bbox": [west, south, east, north], "features": geo_features}
    (OUT / "hyderabad_roads_sample.geojson").write_text(json.dumps(geojson, separators=(",", ":")), encoding="utf-8")

    # GeoTIFF keys: geographic model, pixel-is-area, WGS84 longitude/latitude.
    tags = TiffImagePlugin.ImageFileDirectory_v2()
    tags[33550] = ( (east - west) / WIDTH, (north - south) / HEIGHT, 0.0 )
    tags[33922] = (0.0, 0.0, 0.0, west, north, 0.0)
    tags[34735] = (1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326)
    raster.save(OUT / "hyderabad_roads_sample.tif", format="TIFF", tiffinfo=tags, compression="tiff_deflate")
    print(f"Wrote {len(geo_features)} clipped road segments to GeoJSON and GeoTIFF")


if __name__ == "__main__":
    main()
