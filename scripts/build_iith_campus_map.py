"""Build the IITH (Kandi) campus corridor map used by the live demo.

Road centrelines, the campus perimeter and vertiport pads were traced by hand
from the campus map image ``data/iith_campus_map.jpg`` (2576 x 1836 px). Pixel
coordinates are converted to WGS84 with a fixed scale so the image can be drawn
as a georeferenced backdrop in exactly the same frame.

    python scripts/build_iith_campus_map.py   ->  data/iith_campus.geojson

Approximate registration (image centre ~ campus centre, ~0.95 m/px). This is a
schematic campus map, not survey data.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "iith_campus.geojson"
IMAGE = "iith_campus_map.jpg"
W, H = 2576, 1836
M_PER_PX = 0.95
LON0, LAT0 = 78.1236, 17.5940  # approximate campus centre

# --- main (white) roads ---------------------------------------------------------
PRIMARY = [
    [(0, 767), (120, 767), (250, 690), (640, 682), (675, 700), (693, 762)],                 # Main Gate -> R1
    [(693, 762), (720, 800), (800, 905), (880, 1040), (920, 1150), (960, 1212),
     (1270, 1215), (1310, 1195), (1632, 1188)],                                             # R1 -> Admin Block -> R4
    [(693, 762), (640, 800), (625, 830), (622, 1205), (770, 1205), (772, 1345),
     (800, 1358), (1140, 1280), (1637, 1275)],                                              # Hospital loop / south boundary
    [(510, 500), (510, 682)],                                                               # Guest House spur
    [(430, 682), (430, 848), (380, 858), (380, 1245), (615, 1245), (622, 1205)],             # west lots
    [(1262, 480), (1268, 415), (1637, 418)],                                                # R2 -> north
    [(1268, 415), (1300, 320), (1515, 315), (1490, 412)],                                   # north loop
    [(1262, 480), (1300, 555), (1632, 558)],                                                # R2 -> R3
    [(1637, 418), (1632, 558), (1637, 727), (1637, 855), (1637, 1055), (1632, 1188),
     (1637, 1275), (1640, 1390), (1590, 1410), (1500, 1610)],                               # central spine
    [(1640, 1390), (1795, 1395), (1795, 1550), (1740, 1625)],                               # south exit
    [(1637, 418), (1800, 415), (1830, 440), (1845, 690), (1960, 685), (1975, 760),
     (2150, 762), (2440, 758), (2470, 785), (2478, 1000), (2460, 1080)],                    # north-east ring
    [(1637, 727), (1810, 730), (1900, 840), (2190, 855)],                                   # -> R5
    [(2190, 855), (2260, 765)],
    [(2190, 855), (2120, 940), (2110, 1100), (2110, 1380)],                                 # SNCC road
    [(1795, 1385), (2110, 1382)],                                                           # Mess A south
]
# --- internal (beige) paths -----------------------------------------------------
TERTIARY = [
    [(760, 420), (1100, 420), (1150, 470), (1262, 480)],
    [(760, 420), (760, 748)],
    [(925, 420), (925, 748)],
    [(700, 748), (1145, 748)],
    [(1145, 470), (1145, 748), (1145, 1055)],
    [(1145, 668), (1630, 668)],
    [(1240, 815), (1340, 812), (1500, 820), (1630, 800)],
    [(1240, 748), (1240, 815), (1240, 1055)],
    [(880, 1055), (1145, 1055), (1240, 1055), (1637, 1055)],
    [(1637, 855), (1720, 855), (1720, 1045), (1985, 1045), (2110, 1045)],
    [(1985, 860), (1985, 1045)],
    [(1720, 955), (1800, 955)],
    [(1632, 1188), (1720, 1190), (2110, 1190)],
]
# --- campus perimeter (geofence) ------------------------------------------------
PERIMETER = [
    (0, 735), (45, 735), (50, 480), (315, 455), (365, 495), (515, 495), (520, 450),
    (740, 450), (750, 400), (1080, 400), (1140, 455), (1240, 470), (1285, 305),
    (1525, 300), (1500, 405), (1820, 400), (1850, 435), (1865, 680), (1965, 675),
    (1985, 745), (2455, 745), (2485, 775), (2495, 1010), (2470, 1100), (2545, 1260),
    (2545, 1510), (2160, 1420), (1810, 1370), (1810, 1560), (1745, 1640), (1480, 1625),
    (1575, 1395), (1630, 1390), (1625, 1290), (1140, 1295), (800, 1375), (760, 1360),
    (755, 1220), (640, 1220), (630, 1265), (360, 1265), (360, 870), (100, 960),
    (50, 870), (45, 800), (0, 800),
]
# --- vertiport pads (on buildings) ----------------------------------------------
VERTIPORTS = [
    ("V1", "Hospital", "hospital", (668, 1035)),
    ("V2", "Main Gate", "hub", (150, 630)),
    ("V3", "Guest House", "hub", (590, 560)),
    ("V4", "Convention Centre", "hub", (830, 670)),
    ("V5", "LHC", "hub", (1205, 925)),
    ("V6", "Admin Block", "hub", (1110, 1120)),
    ("V7", "Academic Area", "hub", (1430, 1090)),
    ("V8", "Mess B", "depot", (1745, 915)),
    ("V9", "New Hostels", "hub", (1880, 975)),
    ("V10", "Mess A", "depot", (1830, 1245)),
    ("V11", "Old Hostels", "hub", (1700, 1320)),
    ("V12", "SNCC", "hub", (2200, 1080)),
    ("V13", "Sampoorna", "depot", (330, 570)),
]


def to_lonlat(px: float, py: float) -> list[float]:
    x = (px - W / 2) * M_PER_PX
    y = (H / 2 - py) * M_PER_PX
    lon = LON0 + x / (111_320.0 * math.cos(math.radians(LAT0)))
    lat = LAT0 + y / 111_132.0
    return [round(lon, 7), round(lat, 7)]


def _inside(pt, poly) -> bool:
    x, y = pt
    c = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def main() -> None:
    feats = []
    for cls, lines in (("primary", PRIMARY), ("tertiary", TERTIARY)):
        for k, line in enumerate(lines):
            feats.append({"type": "Feature", "id": f"{cls}/{k}",
                          "properties": {"highway": cls, "source": "traced from IITH campus map"},
                          "geometry": {"type": "LineString", "coordinates": [to_lonlat(*p) for p in line]}})
    ring = [to_lonlat(*p) for p in PERIMETER]
    feats.append({"type": "Feature", "id": "geofence", "properties": {"geofence": True, "name": "IITH campus boundary"},
                  "geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]}})
    for vid, name, role, p in VERTIPORTS:
        assert _inside(p, PERIMETER), f"{name} pad outside campus"
        feats.append({"type": "Feature", "id": vid, "properties": {"vertiport": role, "name": name, "ref": vid},
                      "geometry": {"type": "Point", "coordinates": to_lonlat(*p)}})
    outside = [p for line in PRIMARY + TERTIARY for p in line if not _inside(p, PERIMETER) and p[0] > 0]
    if outside:
        print("warning: road vertices outside perimeter:", outside)
    west, north = to_lonlat(0, 0)
    east, south = to_lonlat(W, H)
    data = {
        "type": "FeatureCollection",
        "name": "IITH campus corridor map",
        "junction_snap_m": 16.0,
        "bbox": [west, south, east, north],
        "backdrop": {"image": IMAGE, "bbox": [west, south, east, north],
                     "attribution": "Campus map © Indian Institute of Technology Hyderabad"},
        "features": feats,
    }
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"wrote {OUT} ({len(feats)} features)")


if __name__ == "__main__":
    main()
