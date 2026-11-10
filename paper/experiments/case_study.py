"""Section VIII-F case study: the battery_failure preset with the final code.

Prints the event timeline of the two scripted cargo drones and the run statistics and writes
results/case_study.json and results/case_study.txt.
"""
import sys, json, io, contextlib
import paths
from web_sandbox.server import prepare_live_run
from simulation.route_engine import simulate_routes
p = prepare_live_run({"preset": "battery_failure", "variant": 0})
names = p["preset"]["names"]; c1, c2 = names["cargo1"], names["cargo2"]
ev = []; st = {}
for fr in simulate_routes(p["network"], p["flights"], p["duration"], config=p["config"], use_overseer=p["use_overseer"],
                          use_admm=p["use_admm"], defended=p["defended"], attack_config=p["attack"],
                          overseer_link_config=p["link"], frame_every=p["stride"], seed=p["seed"]):
    ev += fr["events"]; st = fr.get("stats", st)
buf = io.StringIO()
keep = [(e["t"], e["kind"], e["text"]) for e in ev if (set(e.get("ids") or []) & {c1, c2}) and e["kind"] in ("bms", "divert", "dtc", "land", "forced", "console", "replan")]
keep += [(e["t"], e["kind"], e["text"]) for e in ev if e["kind"] == "hold" and "holds short" in e["text"]]
with contextlib.redirect_stdout(buf):
    for k in sorted(keep): print(k)
    print({k: st.get(k) for k in ("arrivals", "delivered", "diversions", "forced_landings", "precautionary_landings", "pads_held_short", "energy_depleted", "near_misses", "min_separation_m")})
print(buf.getvalue(), end="")
(paths.RESULTS / "case_study.txt").write_text(buf.getvalue())
json.dump({"events": sorted(keep), "stats": st, "c1": c1, "c2": c2}, open(paths.RESULTS / "case_study.json", "w"), default=str)
