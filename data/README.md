# Hyderabad open map sample

This is a small road-map demo sample for the MASooda live dashboard.

- Coverage: 78.350–78.380° E, 17.430–17.450° N (Hyderabad, Telangana).
- Source: OpenStreetMap API road features (`highway=*`), bounding-box extract fetched 2026-11-06.
- Files: `hyderabad_roads_sample.geojson` contains clipped road centerlines; `hyderabad_roads_sample.tif` is a rendered GeoTIFF backdrop of those same roads.
- Attribution: © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), available under the Open Database License (ODbL).
- Rebuild: place the original OSM API XML bounding-box extract at `data/hyderabad_roads_sample.osm`, then run `python scripts/prepare_hyderabad_map_sample.py` (Pillow is required to write the TIFF).

The raster is for visualization. GeoJSON centerlines are the vector road layer. Neither dataset supplies road widths, obstacle heights, population exposure, flight permissions, or surveyed safety-grade geometry. OSM completeness and positional accuracy are not guaranteed. The dashboard registers the geographic sample center to simulation-local `(x, y) = (0, 0)` and converts nearby longitude/latitude to local metres. This registration is a demonstration transform; generated flight paths are not yet constrained to road corridors.
