"""Bake a scenario into a replayable run file for the live demo's "⤒ Load" button.

The run goes through the same code path as the website (web_sandbox.server.start_live_run ->
_run_worker -> build_export), so the file is byte-for-byte the format the site downloads with
"⤓ Run", and the site replays it without simulating anything.

    python demo/bake_demo.py                                  # hierarchical showcase run
    python demo/bake_demo.py --architecture decentralized_undefended
    python demo/bake_demo.py --all                            # all four architectures + summary
    python demo/bake_demo.py --preset summer_ops              # any preset in data/scenarios/

Outputs go to demo/baked/: masooda_showcase_<arch>.json (load this on the site) and
showcase_summary.json / showcase_summary.md (final KPIs per architecture).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import web_sandbox.server as server  # noqa: E402
from simulation.scenario_presets import build_preset_request  # noqa: E402
from web_sandbox.run_export import build_export  # noqa: E402

SCENARIO = Path(__file__).with_name("showcase_scenario.json")
OUT = Path(__file__).with_name("baked")
ARCHS = ("hierarchical", "centralized", "decentralized", "decentralized_undefended")
# drones whose full health detail (cell voltages, temperatures, EKF) is recorded in every frame
DETAIL = ("blood1", "cargo1", "cargo2", "hot1", "gnss1", "courier")


def bake(arch: str, scenario: Path = SCENARIO, tag: str = "", name: str = "showcase") -> dict:
    preset = json.loads(scenario.read_text(encoding="utf-8"))
    preset["request"]["architecture"] = arch
    server.load_preset = lambda _id: preset          # serve this file as the preset
    typed = [e for e in preset.get("script", []) if "targets_type" in e]
    if typed:   # "targets_type": ["DELIVERY", ...] -> every random-fleet drone of those types (ids fixed by the seed)
        preset["script"] = [e for e in preset["script"] if "targets_type" not in e]
        flights = server.prepare_live_run({"preset": preset["id"]})["flights"]
        for e in typed:
            want = set(e.pop("targets_type"))
            e["targets"] = sorted(f.agent_id for f in flights if f.type.value in want and not f.custom)
        preset["script"] += typed
    _, _, names = build_preset_request(preset)
    detail = [names[n] for n in DETAIL if n in names]
    if not detail:   # other presets: every named drone with a fault, a set charge or a payload (cell detail)
        detail = [names[r["name"]] for r in preset.get("drones", []) if r.get("name") in names
                  and ("fault" in r or "soc_init_pct" in r or "payload_kg" in r)]
    original_init = server.LiveRun.__init__

    def init(self, *a, **k):
        original_init(self, *a, **k)
        self.sel = list(detail)
    server.LiveRun.__init__ = init
    try:
        t0 = time.time()
        start = server.start_live_run({"preset": preset["id"]})
        run = server.RUNS[start["run_id"]]
        while not run.done:
            time.sleep(0.5)
        run.thread.join()
    finally:
        server.LiveRun.__init__ = original_init
    if run.error:
        raise RuntimeError(run.error)
    frames, _ = run.store.since(0, 10**9)
    export = build_export(run.manifest, run.request, run.config, frames, run.commands,
                          complete=run.stop_reason is None, thinned=run.store.thinned)
    export = server._json_safe(export)
    OUT.mkdir(exist_ok=True)
    path = OUT / f"masooda_{name}_{arch}{tag}.json"
    path.write_text(json.dumps(export, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    last = export["kpis"][-1]
    emerg = [f for f in run.manifest["flights"] if f["type"] == "EMERGENCY"]
    print(f"{arch}: {len(frames)} frames, {len(export['events'])} events, {path.stat().st_size / 1e6:.1f} MB, "
          f"{time.time() - t0:.0f} s wall")
    return {"architecture": arch, "file": path.name, "frames": len(frames), "events": len(export["events"]),
            "commands": len(run.commands), "flights": len(run.manifest["flights"]), "emergency_flights": len(emerg),
            "config_hash": export["config_hash"], "ic_hash": run.manifest["ic_hash"], "names": names,
            "final": last}


def write_summary(results: list[dict]) -> None:
    keys = ("drones_inside_active_restricted_area", "operator_commands_applied", "delivered", "arrivals", "crashes", "near_misses", "min_separation_m", "safety_violation_ticks",
            "priority_compliance", "emergency_mean_delay_s", "spoofed_reports_accepted", "reports_dropped",
            "admm_events", "admm_nonconverged", "admm_it_p95", "dtc_directives", "layer_changes", "pad_holds",
            "diversions", "forced_landings", "energy_depleted", "bms_alerts", "energy_used_wh",
            "energy_per_delivered_wh", "max_pack_c", "max_motor_c", "merge_success_rate", "platoons")
    (OUT / "showcase_summary.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    lines = ["| KPI | " + " | ".join(r["architecture"] for r in results) + " |",
             "|---|" + "---|" * len(results)]
    for k in keys:
        cells = []
        for r in results:
            v = r["final"].get(k)
            cells.append("—" if v is None else f"{v:.2f}" if isinstance(v, float) else str(v))
        lines.append(f"| {k} | " + " | ".join(cells) + " |")
    (OUT / "showcase_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def compliance(d: dict) -> dict:
    """Rule-following KPIs the engine does not count: drones airborne inside an active restricted
    area (including drones still flying out of it) and operator commands the architecture applied."""
    import numpy as np
    from simulation.dtc_console import points_in_polygon
    zones = [c["params"] for c in d["commands"] if c["type"] == "tfr"]
    inside = set()
    for f in d["frames"]:
        active = [z["polygon"] for z in zones if z["start_s"] <= f["t"] <= z["end_s"]]
        if not active:
            continue
        xy = np.c_[np.asarray(f["x"]) / 10.0, np.asarray(f["y"]) / 10.0]   # compact frames store decimetres
        air = np.array([(v >> 3) == 1 for v in f["ls"]])
        for poly in active:
            inside |= set(np.nonzero(points_in_polygon(xy, poly) & air)[0].tolist())
    applied = sum(1 for c in d["commands"] if "no DTC" not in str(c.get("outcome")))
    return {"drones_inside_active_restricted_area": len(inside),
            "operator_commands_applied": f"{applied}/{len(d['commands'])}"}


def summarize_files() -> None:
    """Rebuild the summary from the baked files (no simulation)."""
    out = []
    for arch in ARCHS:
        path = OUT / f"masooda_showcase_{arch}.json"
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            out.append({"architecture": arch, "file": path.name, "frames": len(d["frames"]),
                        "events": len(d["events"]), "commands": len(d["commands"]),
                        "flights": len(d["manifest"]["flights"]), "config_hash": d["config_hash"],
                        "ic_hash": d["manifest"]["ic_hash"], "final": {**d["kpis"][-1], **compliance(d)}})
    write_summary(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--architecture", default="hierarchical", choices=ARCHS)
    ap.add_argument("--all", action="store_true", help="bake all four architectures and write the summary")
    ap.add_argument("--scenario", type=Path, default=SCENARIO)
    ap.add_argument("--tag", default="", help="suffix for the output file name (trial runs; no summary)")
    ap.add_argument("--preset", help="bake data/scenarios/<id>.json instead of the showcase (no summary)")
    ap.add_argument("--summary-only", action="store_true", help="rebuild the summary from the baked files")
    a = ap.parse_args()
    if a.summary_only:
        summarize_files()
        return
    if a.preset:
        for x in (ARCHS if a.all else (a.architecture,)):
            bake(x, ROOT / "data" / "scenarios" / f"{a.preset}.json", a.tag, a.preset)
        return
    results = [bake(x, a.scenario, a.tag) for x in (ARCHS if a.all else (a.architecture,))]
    if a.tag:
        return
    if a.all or not (OUT / "showcase_summary.json").exists():
        write_summary(results)
    else:
        old = {r["architecture"]: r for r in json.loads((OUT / "showcase_summary.json").read_text())}
        old.update({r["architecture"]: r for r in results})
        write_summary([old[k] for k in ARCHS if k in old])


if __name__ == "__main__":
    main()
