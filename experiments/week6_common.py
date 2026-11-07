"""Helpers shared by the Week 6 experiment scripts (scripts/week6_*.py).

* :func:`run_matrices` runs one or more matrices of ``experiments.week6.matrices``
  into one folder through :func:`experiments.week6.run_matrix` and writes one
  merged ``manifest.json``.
* :func:`weak_groups` lists summary groups that are too thin or too noisy
  (``experiments.week6.weak``); scripts only *list* them, never re-run.
* :func:`md_summary_table` renders a README table from ``summary.csv`` rows.
  Every table carries a marker comment so :func:`check_readme_tables` can
  regenerate it from the CSV and detect any mismatch.

Missing values are written "n/a", never 0.
"""

from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
import platform
import re
import time
from typing import Any, Iterable, Mapping, Sequence

from experiments.week6 import (
    REPO_ROOT,
    aggregate,
    config_hash,
    expand_matrix,
    git_commit,
    read_rows,
    run_matrix,
    week6_config,
    write_csv,
    write_manifest,
    _versions,
)

# --------------------------------------------------------------------------- paths


def week6_root(quick: bool = False) -> Path:
    w6 = week6_config()
    base = REPO_ROOT / str(w6.get("output_dir", "outputs/week6"))
    if quick:
        base = base / str((w6.get("quick", {}) or {}).get("subdir", "_quick"))
    return base


def exp_dir(subdir: str, quick: bool = False) -> Path:
    return week6_root(quick) / subdir


def fig_dir(quick: bool = False) -> Path:
    return week6_root(quick) / "figures"


# --------------------------------------------------------------------------- running


def run_matrices(
    names: Sequence[str],
    quick: bool = False,
    workers: int | None = None,
    resume: bool = True,
    log=print,
    max_runs: int | None = None,
) -> tuple[Path, list, list[dict]]:
    """Run matrices that share one ``output_subdir``; return (out_dir, specs, rows).

    Specs shared between matrices (same spec hash) run once. ``rows`` are the
    runs.csv rows of exactly these specs, in spec order. ``max_runs`` caps the
    number of simulations executed by this call across all matrices (the rest
    stay pending for a resumed call).
    """
    t0 = time.perf_counter()
    all_specs: list = []
    sections: dict[str, Any] = {}
    resolved: dict[str, Any] = {}
    per_matrix: dict[str, Any] = {}
    out_dir: Path | None = None
    executed = 0
    deferred_total = 0
    for name in names:
        specs, used, raw = expand_matrix(name, quick=quick)
        d = exp_dir(str(used["output_subdir"]), quick)
        if out_dir is not None and d != out_dir:
            raise ValueError(f"matrices {list(names)} do not share one output_subdir")
        out_dir = d
        sections[f"experiments.week6.matrices.{name}"] = raw
        resolved[name] = used
        log(f"[week6] matrix {name}: {len(specs)} specs -> {d}")
        tm = time.perf_counter()
        # --fresh clears the folder once; later matrices in it must resume.
        budget = None if max_runs is None else max(0, int(max_runs) - executed)
        run_matrix(specs, d, workers=workers, resume=resume or name != names[0], log=log, max_runs=budget)
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        executed += int(man.get("n_run") or 0) + len(man.get("failures") or [])
        deferred_total += int(man.get("n_deferred_max_runs") or 0)
        per_matrix[name] = {
            "n_specs": man.get("n_specs"),
            "n_run": man.get("n_run"),
            "n_skipped_resume": man.get("n_skipped_resume"),
            "failures": man.get("failures"),
            "identical_initial_conditions": man.get("identical_initial_conditions"),
            "wall_time_s": round(time.perf_counter() - tm, 3),
            "per_run_wall_time_s": man.get("per_run_wall_time_s"),
        }
        all_specs.extend(specs)
    assert out_dir is not None
    rows = rows_for_specs(out_dir / "runs.csv", all_specs)
    from experiments.week6 import check_identical_conditions_week6

    ok, msg = check_identical_conditions_week6(rows)
    write_manifest(
        out_dir / "runs.csv",
        {
            "matrices": list(names),
            "quick": bool(quick),
            "config_section": sections,
            "config_section_resolved": resolved,
            "per_matrix": per_matrix,
            "seeds": sorted({int(s.seed) for s in all_specs}),
            "agent_counts": sorted({int(s.n_agents) for s in all_specs}),
            "architectures": sorted({s.architecture for s in all_specs}),
            "n_specs_unique": len({s.spec_hash() for s in all_specs}),
            "identical_initial_conditions": {"ok": ok, "message": msg},
            "failures": [f for m in per_matrix.values() for f in (m.get("failures") or [])],
            "pending_after_this_call": deferred_total,
            "wall_time_s": round(time.perf_counter() - t0, 3),
            "provisional": bool(week6_config().get("provisional", True)),
            "hardware": hardware_info(),
        },
    )
    return out_dir, all_specs, rows


def rows_for_specs(runs_csv: str | Path, specs: Sequence) -> list[dict]:
    """runs.csv rows (current base config) for ``specs``, de-duplicated, in spec order."""
    current = config_hash()
    by_hash = {r["spec_hash"]: r for r in read_rows(runs_csv) if r.get("base_config_hash") == current}
    out, seen = [], set()
    for s in specs:
        h = s.spec_hash()
        if h in by_hash and h not in seen:
            seen.add(h)
            out.append(by_hash[h])
    return out


def update_manifest(out_dir: Path, extra: Mapping[str, Any]) -> None:
    p = Path(out_dir) / "manifest.json"
    man = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    man.update(extra)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(man, f, indent=2, sort_keys=True, default=str)
        f.write("\n")


def aggregate_rows(
    rows: Sequence[Mapping[str, Any]],
    out_dir: Path,
    group_by: Sequence[str],
    metrics: Sequence[str],
    name: str = "summary.csv",
    source_name: str = "_rows_for_summary.csv",
) -> list[dict]:
    """Aggregate an explicit row list (e.g. only this experiment's specs)."""
    cols = list(dict.fromkeys(list(group_by) + list(metrics)))
    src = Path(out_dir) / source_name
    write_csv(rows, src, cols)
    try:
        return aggregate(src, group_by, metrics, out_csv=Path(out_dir) / name)
    finally:
        src.unlink(missing_ok=True)


# --------------------------------------------------------------------------- weak groups


def weak_groups(
    summary_rows: Sequence[Mapping[str, Any]],
    group_by: Sequence[str],
    metrics: Sequence[str],
) -> list[dict]:
    """Groups with fewer than ``weak.min_n`` values or std/|mean| > ``weak.max_cv``."""
    w = week6_config().get("weak", {}) or {}
    min_n = int(w.get("min_n", 3))
    max_cv = float(w.get("max_cv", 0.5))
    out = []
    for r in summary_rows:
        reasons = []
        for m in metrics:
            n = int(_f(r.get(f"{m}_n")) or 0) if math.isfinite(_f(r.get(f"{m}_n"))) else 0
            mean, std = _f(r.get(f"{m}_mean")), _f(r.get(f"{m}_std"))
            if n < min_n:
                reasons.append(f"{m}: n={n} < {min_n}")
            elif math.isfinite(mean) and math.isfinite(std) and abs(mean) > 0 and std / abs(mean) > max_cv:
                reasons.append(f"{m}: std/mean={std / abs(mean):.2f} > {max_cv}")
        if reasons:
            out.append({"group": {g: r.get(g) for g in group_by}, "reasons": reasons})
    return out


def write_weak(out_dir: Path, weak: list[dict], criteria_metrics: Sequence[str]) -> Path:
    w = week6_config().get("weak", {}) or {}
    p = Path(out_dir) / "weak_results.json"
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(
            {
                "criteria": {"min_n": int(w.get("min_n", 3)), "max_cv": float(w.get("max_cv", 0.5)),
                             "metrics": list(criteria_metrics)},
                "action": "listed only; not re-run",
                "weak_groups": weak,
            },
            f, indent=2, sort_keys=True, default=str,
        )
        f.write("\n")
    return p


# --------------------------------------------------------------------------- formatting


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def fmt(v: Any, sig: int = 4) -> str:
    """Number for a README cell: 'n/a' for NaN/empty, ints as ints, else 4 s.f."""
    if v is None or (isinstance(v, str) and v.strip() in ("", "nan", "NaN", "None")):
        return "n/a"
    if isinstance(v, bool) or (isinstance(v, str) and v in ("True", "False")):
        return str(v)
    x = _f(v)
    if isinstance(v, str) and math.isnan(x):  # a label such as an architecture name
        return v
    if not math.isfinite(x):
        return "n/a" if math.isnan(x) else ("inf" if x > 0 else "-inf")
    if float(x).is_integer() and abs(x) < 1e9:
        return str(int(x))
    return f"{x:.{sig}g}"


def fmt_ci(row: Mapping[str, Any], metric: str) -> str:
    """'mean ± half-CI (n=k)' from summary columns; 'n/a' when n = 0."""
    n = _f(row.get(f"{metric}_n"))
    mean = _f(row.get(f"{metric}_mean"))
    if not math.isfinite(mean) or not math.isfinite(n) or n == 0:
        return "n/a"
    lo, hi = _f(row.get(f"{metric}_ci_lo")), _f(row.get(f"{metric}_ci_hi"))
    if math.isfinite(lo) and math.isfinite(hi):
        return f"{fmt(mean)} ± {fmt((hi - lo) / 2.0, 2)} (n={int(n)})"
    return f"{fmt(mean)} (n={int(n)})"


def md_table(header: Sequence[str], body: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    return "\n".join(lines)


_MARK = "<!-- table src={src} group_by={g} metrics={m}{flt} -->"


def md_summary_table(
    summary_rows: Sequence[Mapping[str, Any]],
    group_by: Sequence[str],
    metrics: Sequence[str],
    src: str = "summary.csv",
    where: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
) -> str:
    """Markdown table (mean ± 95% CI half-width, n) generated from summary rows.

    The leading marker comment records source, columns and filter so
    :func:`check_readme_tables` can regenerate and compare it.
    """
    labels = labels or {}
    rows = [r for r in summary_rows if all(str(r.get(k)) == str(v) for k, v in (where or {}).items())]
    header = [labels.get(g, g) for g in group_by] + [labels.get(m, m) for m in metrics]
    body = [[fmt(r.get(g)) for g in group_by] + [fmt_ci(r, m) for m in metrics] for r in rows]
    flt = "" if not where else " where=" + ",".join(f"{k}:{v}" for k, v in where.items())
    marker = _MARK.format(src=src, g=",".join(group_by), m=",".join(metrics), flt=flt)
    return marker + "\n" + md_table(header, body)


_MARK_RE = re.compile(r"<!-- table src=(\S+) group_by=(\S*) metrics=(\S+)(?: where=(\S+))? -->\n((?:\|.*\n?)+)")


def check_readme_tables(readme: str | Path) -> list[str]:
    """Regenerate every marked table in ``readme`` from its CSV; return mismatches."""
    readme = Path(readme)
    text = readme.read_text(encoding="utf-8")
    problems = []
    for m in _MARK_RE.finditer(text):
        src, g, mets, where, table = m.groups()
        csv_path = readme.parent / src
        if not csv_path.is_file():
            problems.append(f"{readme.name}: source {src} missing")
            continue
        rows = read_rows(csv_path)
        wh = dict(kv.split(":", 1) for kv in where.split(",")) if where else None
        g_list = [x for x in g.split(",") if x]
        expected = md_summary_table(rows, g_list, mets.split(","), src=src, where=wh).split("\n", 1)[1]
        got_lines = [ln for ln in table.strip().split("\n")]
        exp_lines = expected.strip().split("\n")
        if [_cells(x) for x in got_lines[2:]] != [_cells(x) for x in exp_lines[2:]]:
            problems.append(f"{readme.name}: table from {src} ({mets}) does not match the CSV")
    return problems


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


# --------------------------------------------------------------------------- README bits


def hardware_info() -> dict[str, Any]:
    return {
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
    }


def manifest_lines(out_dir: Path) -> list[str]:
    man = json.loads((Path(out_dir) / "manifest.json").read_text(encoding="utf-8"))
    hw = man.get("hardware") or hardware_info()
    v = man.get("versions") or _versions()
    return [
        f"- Matrices: {', '.join(man.get('matrices', [man.get('matrix', '?')]))}"
        f" ({man.get('n_specs_unique', man.get('n_specs', '?'))} unique runs); seeds {man.get('seeds')};"
        f" N = {man.get('agent_counts')}",
        f"- Commit `{man.get('git_commit')}`, config hash `{man.get('config_hash')}`,"
        f" generated {man.get('timestamp')}",
        f"- Hardware: {hw.get('os')}, {hw.get('processor')}, {hw.get('cpu_count')} logical CPUs;"
        f" Python {v.get('python')}, numpy {v.get('numpy')}, matplotlib {v.get('matplotlib')}",
        f"- Wall time of the last run invocation: {fmt(man.get('wall_time_s'))} s"
        f" (runs resumed from earlier invocations are not re-timed)",
        f"- Identical initial conditions per (seed, N): "
        f"{'yes' if (man.get('identical_initial_conditions') or {}).get('ok') else 'NO'}",
    ]


def weak_lines(out_dir: Path) -> list[str]:
    p = Path(out_dir) / "weak_results.json"
    if not p.is_file():
        return ["- (no weak_results.json)"]
    data = json.loads(p.read_text(encoding="utf-8"))
    groups = data.get("weak_groups", [])
    if not groups:
        return ["- None: every group has at least "
                f"{data['criteria']['min_n']} values and std/mean ≤ {data['criteria']['max_cv']}."]
    out = [f"Criteria: n < {data['criteria']['min_n']} or std/mean > {data['criteria']['max_cv']} "
           f"on {', '.join(data['criteria']['metrics'])}. Listed only, not re-run."]
    for g in groups:
        key = ", ".join(f"{k}={v}" for k, v in g["group"].items())
        out.append(f"- {key}: {'; '.join(g['reasons'])}")
    return out


def provisional_banner() -> str:
    if bool(week6_config().get("provisional", True)):
        return "> **PROVISIONAL — pre-bug-fix results.** Metric and attack code is still being fixed.\n"
    return ""


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return path


def find_summary(rows: Sequence[Mapping[str, Any]], **match: Any) -> Mapping[str, Any] | None:
    for r in rows:
        if all(str(r.get(k)) == str(v) for k, v in match.items()):
            return r
    return None


def common_args(ap) -> None:
    ap.add_argument("--quick", action="store_true", help="smoke test (outputs under outputs/week6/_quick)")
    ap.add_argument("--workers", type=int, default=None, help="process count (default os.cpu_count())")
    ap.add_argument("--fresh", action="store_true", help="ignore existing runs.csv (no resume)")
    ap.add_argument("--max-runs", type=int, default=None,
                    help="run at most this many simulations now; call again to resume the rest")


def sorted_num(values: Iterable[Any]) -> list:
    vals = list(dict.fromkeys(values))
    try:
        return sorted(vals, key=lambda v: float(v))
    except (TypeError, ValueError):
        return sorted(vals, key=str)
