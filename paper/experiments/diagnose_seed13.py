"""Diagnostic behind the seed-13 forced landing (Sections VIII-C and IX).

Replays the battery-fault scenario, seed 13, with the full manager and with the health-blind manager
and prints every event that involves the two cell-failure drones (ids 100 and 101), plus the hold-short
events. Writes results/diagnostics/seed13_full.txt and results/diagnostics/seed13_blind.txt.
"""
import paths
import paper_experiments as pe
from web_sandbox.server import prepare_live_run
from simulation.route_engine import simulate_routes

WATCH = {100, 101}
paths.DIAG.mkdir(parents=True, exist_ok=True)
for manager in ("full", "blind"):
    body = pe.scenario_body("faults", 13, 100)
    body["config"] = pe._merge(pe._merge(body["config"], pe.MANAGER[manager]), pe.KNOWLEDGE["ekf"])
    p = prepare_live_run(body)
    out = []
    for fr in simulate_routes(p["network"], p["flights"], p["duration"], config=p["config"],
                              use_overseer=p["use_overseer"], use_admm=p["use_admm"], defended=p["defended"],
                              attack_config=p["attack"], overseer_link_config=p["link"], frame_every=p["stride"],
                              architecture=p["architecture"], seed=p["seed"]):
        for e in fr["events"]:
            ids = set(e.get("ids") or [])
            if ids & WATCH or any(f"D-{i}" in e["text"] for i in WATCH) or "holds short" in e["text"]:
                out.append(f"{e['t']:7.1f}  {e['kind']:8s} {e['text']}")
        last = fr
    out.append("stats: " + str({k: last["stats"].get(k) for k in ("arrivals", "diversions", "forced_landings", "pads_held_short", "near_misses")}))
    txt = "\n".join(out)
    (paths.DIAG / f"seed13_{manager}.txt").write_text(txt + "\n")
    print(f"===== manager = {manager} =====\n{txt}\n")
