# Map import and India road-aware corridor design

**Status:** research prototype design, not an operational flight authorization system. Reviewed 2026-11-06. P2 implementation scope: map import, map/simulation registration, sample data, and corridor architecture proposal.

## What the map means

The live dashboard can display a georeferenced WGS84 GeoTIFF and road centerlines from GeoJSON. It checks that the TIFF has a geographic CRS and georeferencing, projects road coordinates into a local tangent-plane frame around the map center, and displays simulation x/y in that same local frame. The Hyderabad sample uses an origin at its geographic center and labels its source and license.

A TIFF is an image, not a routable network. A raster can show roads, but it does not encode trustworthy intersections, connectivity, road class, right-of-way, or width. Use the accompanying GeoJSON lines for network geometry. Any TIFF without usable embedded georeferencing is rejected by this first version; a later import wizard can accept an explicit CRS plus two or more control points or a world file. The first browser importer supports EPSG:4326 geographic GeoTIFFs; projected CRS support requires a deliberate reprojection path and is not silently guessed.

The local coordinate transform is only a cartographic registration. Existing generated trajectories do not follow the imported roads, and the simulator has no geographic origin in its state. The app must not describe those trajectories as road-following or treat OSM geometry as obstacle/safety-grade data. Map layer import does not change the solver, flight legality, or vehicle behavior.

## Corridor systems reviewed

| System | What the official concept contributes | What MASooda should take from it |
| --- | --- | --- |
| Europe: EASA U-space | U-space airspace is designated by member states using risk assessment; service providers support network identification, geo-awareness, flight authorization, and traffic information. The corridor is not a universal road-following lane. | Keep airspace designation/authorization as a hard external constraint. Keep strategic/real-time traffic services explicit and separate from the geometric route network. |
| United States: FAA UTM | UTM is a collaborative, federated ecosystem for flight-intent exchange, constraint sharing, and strategic deconfliction in low-altitude airspace. FAA UAM ConOps describes corridors as 3D route/volume segments with operational performance assumptions; these are an AAM concept, not a blanket drone rule. | Represent flight intent, shared constraints, reservations, and conformance separately from roads. Model corridors as configurable 3D volumes with capacity and direction when the scenario calls for them. |
| India: Digital Sky / Drone Rules | The Drone Rules establish red, yellow, and green airspace zones and require operators to consult the current airspace map and permissions. DGCA’s July 2025 notice states D-1 through D-5 services are migrating to eGCA. | Import the current lawful zone/permission layer only from an authoritative supported feed or user-provided data, track its timestamp, and fail closed when it is missing/stale. Do not infer permission from a clear road map or a research corridor. |

Primary references: [EASA U-space](https://www.easa.europa.eu/en/domains/air-traffic-management/u-space), [FAA UTM](https://www.faa.gov/uas/advanced_operations/traffic_management), [FAA UAM ConOps 2.0](https://www.faa.gov/sites/faa.gov/files/Urban-Air-Mobility-Concept-of-Operations-2.0.pdf), [India Drone Rules 2021](https://digitalsky.dgca.gov.in/assets/files/dronerules.pdf), [DGCA 2025 public notice](https://digitalsky.dgca.gov.in/assets/files/Public-Notice-egca-Drone-Services.pdf).

## Proposed India-specific architecture: Bharat Road-Linked Airspace Network (BRAN)

BRAN is a project proposal, not a current national corridor standard. It uses roads as one candidate planning backbone while preserving independent airspace, risk, and traffic constraints:

1. **Regulatory and temporary constraint layer.** Red/yellow/green zones, airport-related constraints, time-bounded restrictions, event notices, and authorizations. Each feature needs source, authority, effective time, expiry, and confidence. It is a no-fly/permission filter, not a visual suggestion.
2. **Urban ground context.** Road/rail/river/utility centerlines, buildings, obstacle height where trustworthy, population/activity exposure, hospitals, depots, and candidate take-off/landing sites. Road proximity may help route organization; it does not imply the road is safe to overfly.
3. **Candidate corridor graph.** Nodes are verified junction/transfer/landing points; edges carry a 3D shape, width, permitted direction, vehicle compatibility, capacity model, and evidence/source. Candidate types: critical-response links, high-demand backbone, local feeder, and time-window/event corridors. No widths or altitude bands should be asserted until measured/approved.
4. **Four-dimensional operations.** A reservation is `(route segment, altitude band, entry time, duration)` plus vehicle envelope, payload/mission class, contingency route, priority, and communication assumptions. Emergency priority may request preemption, but never bypasses regulatory or minimum-separation constraints.
5. **Local coordination and monitoring.** The MASooda local planner handles tactical separation within permitted reservations; the overseer manages network contention; independent monitors flag separation, route/volume deviation, stale constraints, and communication loss.

India-relevant scenario parameters should be user-controlled and evidence-backed: medical urgency; mixed delivery/passenger/inspection fleets; dense and irregular built-up areas; overhead-wire/structure obstacles; monsoon wind/rain and flood disruption; temporary crowd/event buffers; local service locations; and Digital Sky/eGCA constraint snapshots. These are inputs to assess, not defaults to claim as nationally valid.

## Data and implementation path

1. Accept GeoTIFF (`.tif/.tiff`) for a visual backdrop and GeoJSON line features for a road network. GeoTIFF needs embedded CRS/geotransform; GeoJSON roads are expected in WGS84 longitude/latitude. Reject absent/unsupported CRS instead of guessing.
2. Read TIFF pixels and bounds locally in the browser. For a research demo, local processing avoids uploading potentially sensitive geospatial files to a remote service. Show the CRS, bounds, source, date, and attribution beside the layer.
3. Register the map center to local simulation `(0,0)` in metres using a local tangent approximation for small areas. For larger areas or engineering use, replace that approximation with a supported projected CRS (e.g. UTM zone selected from the map) and test the transform against known control points.
4. Keep road centerlines as vector geometry. Build a graph only after snapping endpoints within a documented tolerance, retaining one-way/access/class tags, and checking connectivity. Keep the raster solely as a backdrop.
5. Add a map-matching/route-following mode only after implementing waypoint/polyline navigation in simulation state and dynamics. Preserve the current free-flight mode as a separate baseline.
6. Add obstacle-aware routing and flight-zone filtering only with appropriate datasets. Record source/version and explicitly identify missing building heights, wire geometry, exposure, and permissions.

OSM data is licensed under ODbL; retain attribution and review share-alike obligations for derivative databases before publishing. [OpenStreetMap copyright and license](https://www.openstreetmap.org/copyright). OSM is community mapping and is not a safety-critical survey. Survey of India publishes geospatial guidelines; check applicable source, resolution, storage, and dissemination conditions before using higher-accuracy or restricted data. [Survey of India geospatial guidelines](https://onlinemaps.surveyofindia.gov.in/GeospatialGuidelines.aspx).

## Simulation implications and verification gates

Today, the solver uses fixed parallel corridor rectangles in simulation coordinates and scenario generators assign drones to those lanes. The browser map overlay can align the visual context but does not yet alter path planning. The next scientific implementation must introduce explicit waypoint routes/road-graph edges, route assignment, and route-constrained dynamics as an optional mode. The graph must preserve the existing free-flight baseline for comparison.

Before claiming road-aware behavior, demonstrate: (a) known geographic control points map to expected local metres; (b) raster bounds and road vectors overlay the same intersections; (c) every route edge is connected or rejected; (d) simulated drone waypoints lie on assigned edges within a stated tolerance; (e) altitude is displayed with a documented datum/band definition; (f) safety and collision checks operate in the same metric 3D frame; and (g) route performance and safety are compared against the current straight-line baseline. Existing `altitude_layer` is an integer index and `position[2]` is set to that index; it is not currently an absolute altitude in metres or above-ground height.

Do not use the imported sample to claim real-world flight feasibility. It contains road centerlines only and is deliberately small and illustrative.
