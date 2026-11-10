"""Experiments for the paper on BMS-in-the-loop traffic management (route engine, IITH campus map).

Every run is one headless ``simulate_routes`` call built with ``web_sandbox.server.prepare_live_run``,
so it uses exactly the code and validation of the live demo. Arms that share a seed share initial
conditions (paired comparisons).

Suites
  S1  traffic-manager ablation: blind / rule / full  x  nominal, low-SoC fleet, faults, heat wave
  S2  state knowledge: oracle / EKF without margin (z = 0) / EKF with chance margin  x  low-SoC, faults
  S3  architectures: hierarchical / centralized / decentralized / decentralized-undefended (nominal)
  S4  resilience: position-spoofing attack, defended vs undefended (hierarchical)
  S5  scaling: fleet 50 / 100 / 150 / 200 (nominal, hierarchical, full)
  S6  DTC link outage 80-150 s (nominal, hierarchical, full)

Usage:
  python scripts/paper_experiments.py --list
  python scripts/paper_experiments.py --out outputs/paper --workers 2 [--shard 0/2] [--seeds 20]
Results: one JSON line per run in <out>/runs.jsonl (resumable: finished run keys are skipped).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DURATION = 240.0
WINDOW = 90.0
LONG_PAIRS = [("V13", "V12"), ("V2", "V9"), ("V2", "V11"), ("V13", "V10"), ("V3", "V12"), ("V1", "V12"),
              ("V13", "V8"), ("V2", "V10"), ("V3", "V9"), ("V4", "V12")]

MANAGER = {   # what the traffic manager (DTC + ADMM weights) does with health
    "blind": {"drone_health": {"responses": {"dtc_unhealthy_priority": False}}, "admm": {"health_weight": {"enabled": False}}},
    "rule": {"admm": {"health_weight": {"enabled": False}}},
    "full": {},
}
KNOWLEDGE = {  # what the BMS knows
    "oracle": {"drone_health": {"estimator": {"enabled": False}}},
    "ekf_z0": {"drone_health": {"estimator": {"chance_z": 0.0}}},
    "ekf": {},
}


def _merge(a: dict, b: dict) -> dict:
    out = json.loads(json.dumps(a))
    for k, v in b.items():
        out[k] = _merge(out.get(k, {}), v) if isinstance(v, dict) else v
    return out


def _fault_drones(seed: int, kinds: list[str]) -> list[dict]:
    rng = np.random.default_rng([seed, 2027])
    rows = []
    for j, kind in enumerate(kinds):
        o, d = LONG_PAIRS[int(rng.integers(len(LONG_PAIRS)))]
        if rng.random() < 0.5:
            o, d = d, o
        dep = float(np.round(rng.uniform(5.0, 60.0), 1))
        soc = float(np.round(rng.uniform(55.0, 90.0), 0)) if kind != "capacity_loss" else float(np.round(rng.uniform(40.0, 60.0), 0))
        rows.append({"type": "DELIVERY", "origin": o, "destination": d, "depart_s": dep, "soc_init_pct": soc,
                     "fault": {"type": kind, "t_s": round(dep + 45.0, 1)}})
    return rows


def scenario_body(scn: str, seed: int, fleet: int) -> dict:
    body = {"map": "iith", "fleet": fleet, "duration_s": DURATION, "seed": seed, "departure_window_s": WINDOW,
            "config": {}, "drones": []}
    if scn == "lowsoc":
        body["config"] = {"drone_health": {"random_fleet_soc_pct": [15.0, 50.0]}}
    elif scn == "faults":
        body["drones"] = _fault_drones(seed, ["cell_failure", "cell_failure", "capacity_loss", "capacity_loss"])
    elif scn == "heat":
        body["config"] = {"drone_health": {"ambient_c": 44.0, "wind_mps": [2.0, 0.0]}}
        body["drones"] = _fault_drones(seed, ["overheating"] * 4)
    return body


def jobs(seeds: int) -> list[dict]:
    S = list(range(1, seeds + 1))
    out = []

    def add(suite, scn, manager="full", knowledge="ekf", arch="hierarchical", fleet=100, seed=1, extra=None):
        key = f"{scn}|{manager}|{knowledge}|{arch}|N{fleet}|{json.dumps(extra or {}, sort_keys=True)}|s{seed}"
        out.append({"key": key, "suite": suite, "scenario": scn, "manager": manager, "knowledge": knowledge,
                    "architecture": arch, "fleet": fleet, "seed": seed, "extra": extra or {}})

    for s in S:
        for scn in ("nominal", "lowsoc", "faults", "heat"):
            for m in MANAGER:
                add("S1", scn, manager=m, seed=s)
        for scn in ("lowsoc", "faults"):
            for k in ("oracle", "ekf_z0"):
                add("S2", scn, knowledge=k, seed=s)
        for a in ("centralized", "decentralized", "decentralized_undefended"):
            add("S3", "nominal", arch=a, seed=s)
        for defended in (True, False):
            add("S4", "nominal", seed=s, extra={"attack": True, "defended": defended})
    for s in S[: max(1, seeds // 2)]:
        for n in (50, 150, 200):
            add("S5", "nominal", fleet=n, seed=s)
        add("S6", "nominal", seed=s, extra={"outage": True})
    return out


def run_one(job: dict) -> dict:
    from web_sandbox.server import prepare_live_run
    from simulation.route_engine import simulate_routes
    body = scenario_body(job["scenario"], job["seed"], job["fleet"])
    body["config"] = _merge(_merge(body["config"], MANAGER[job["manager"]]), KNOWLEDGE[job["knowledge"]])
    body["architecture"] = job["architecture"]
    ex = job["extra"]
    if ex.get("attack"):
        body["attack"] = {"enabled": True, "count": 2, "start_s": 60.0}
        body["defended"] = bool(ex.get("defended", True))
    if ex.get("outage"):
        body["outage"] = {"enabled": True, "start_s": 80.0, "end_s": 150.0}
    p = prepare_live_run(body)
    fault_ids = [job["fleet"] + j for j in range(len(body["drones"]))]   # custom ids follow the random fleet
    assert all(any(f.agent_id == i and f.custom for f in p["flights"]) for i in fault_ids)
    watch = fault_ids[:4]
    t0 = time.perf_counter()
    stats, prio, admm, last_h = {}, {}, {}, {}
    land_t, forced_t, divert_t, crit_t = {}, {}, {}, {}
    n_frames = 0
    for fr in simulate_routes(p["network"], p["flights"], p["duration"], config=p["config"],
                              use_overseer=p["use_overseer"], use_admm=p["use_admm"], defended=p["defended"],
                              attack_config=p["attack"], overseer_link_config=p["link"], frame_every=p["stride"],
                              architecture=p["architecture"], junction_merge=p.get("junction_merge", True),
                              seed=p["seed"], health_detail_ids=lambda: watch):
        for e in fr["events"]:
            ids = e.get("ids") or []
            i = ids[0] if ids else None
            if i in fault_ids:
                if e["kind"] == "land":
                    land_t.setdefault(i, e["t"])
                elif e["kind"] == "forced":
                    forced_t.setdefault(i, e["t"])
                elif e["kind"] == "divert":
                    divert_t.setdefault(i, e["t"])
                elif e["kind"] == "bms" and ("→ CRITICAL" in e["text"] or "→ FAULT" in e["text"]):
                    crit_t.setdefault(i, e["t"])
        if fr.get("partial"):
            continue
        n_frames += 1
        stats = fr.get("stats", stats)
        prio = fr.get("prio", prio)
        admm = fr.get("admm", admm)
        for k, v in (fr.get("hsel") or {}).items():
            last_h[int(k)] = v
    wall = time.perf_counter() - t0
    fdet = []
    for row, i in zip(body["drones"], fault_ids):
        h = last_h.get(i, {})
        fdet.append({"id": i, "fault": row["fault"]["type"], "t_fault": row["fault"]["t_s"],
                     "land_t": land_t.get(i), "forced_t": forced_t.get(i), "divert_t": divert_t.get(i),
                     "crit_t": crit_t.get(i), "soc_true_last": h.get("soc_true"), "soc_bms_last": h.get("soc"),
                     "watched": i in watch})
    pr = {k: prio.get(k) for k in ("count", "rate", "mean_delay_s", "arrived", "on_time_rate", "mean_ground_hold_s")}
    return {**{k: job[k] for k in ("key", "suite", "scenario", "manager", "knowledge", "architecture", "fleet", "seed")},
            "extra": job["extra"], "flights": len(p["flights"]), "wall_s": round(wall, 2),
            "rtf": round(DURATION / wall, 3), "stats": stats, "prio": pr,
            "admm_run": (admm or {}).get("run", {}), "faults": fdet}


def _safe(job):
    try:
        return run_one(job)
    except Exception as exc:  # keep the batch going; the error is recorded
        import traceback
        return {"key": job["key"], "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "outputs", "paper"))
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--only", default="")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    js = jobs(a.seeds)
    if a.only:
        js = [j for j in js if a.only in j["key"] or a.only == j["suite"]]
    i, n = (int(x) for x in a.shard.split("/"))
    js = [j for k, j in enumerate(js) if k % n == i]
    if a.list:
        print(len(js), "jobs"); [print(j["key"]) for j in js[:20]]; return
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "runs.jsonl")
    done = set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                r = json.loads(line)
                if "error" not in r:
                    done.add(r["key"])
            except ValueError:
                pass
    todo = [j for j in js if j["key"] not in done]
    print(f"{len(todo)} to run ({len(js) - len(todo)} done)", flush=True)
    with Pool(a.workers) as pool, open(path, "a", encoding="utf-8") as fh:
        for r in pool.imap_unordered(_safe, todo):
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            print(r["key"], r.get("wall_s", r.get("error")), flush=True)


if __name__ == "__main__":
    main()
