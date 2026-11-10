"""Fig. 1 (manuscript/fig_map.pdf): the IIT Hyderabad corridor graph from data/iith_campus.geojson."""
import json, matplotlib
import paths
matplotlib.use("Agg")
import matplotlib.pyplot as plt
g = json.load(open(paths.REPO / "data" / "iith_campus.geojson"))
fig, ax = plt.subplots(figsize=(3.5, 2.6))
for f in g["features"]:
    geo, pr = f["geometry"], f.get("properties", {})
    if geo["type"] == "LineString":
        xs, ys = zip(*geo["coordinates"]); ax.plot(xs, ys, color="#6d4fe0", lw=1.1, alpha=0.8)
    elif geo["type"] == "Polygon":
        xs, ys = zip(*geo["coordinates"][0]); ax.plot(xs, ys, "--", color="#d97706", lw=0.8)
for f in g["features"]:
    geo, pr = f["geometry"], f.get("properties", {})
    if geo["type"] == "Point":
        x, y = geo["coordinates"]; role = pr.get("vertiport", "hub")
        c = {"hospital": "#dc2626", "depot": "#ea8c0c"}.get(role, "#0e7490")
        ax.plot(x, y, "s", ms=4, color=c, mec="black", mew=0.4)
        ax.annotate(pr.get("ref", ""), (x, y), xytext=(2, 2), textcoords="offset points", fontsize=5)
ax.set_aspect(1.0 / 0.953); ax.set_xticks([]); ax.set_yticks([])
for s in ax.spines.values(): s.set_visible(False)
fig.tight_layout(pad=0.1); fig.savefig(paths.MANUSCRIPT / "fig_map.pdf", bbox_inches="tight", pad_inches=0.02); print(g["bbox"], [ (f["properties"].get("ref"), f["properties"].get("vertiport")) for f in g["features"] if f["geometry"]["type"]=="Point"][:14])
