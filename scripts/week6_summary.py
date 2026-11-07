"""Consolidated Week 6 results page: outputs/week6/RESULTS.md.

Reads every experiment folder's manifest.json, README.md, summary CSVs and
weak_results.json (no simulation, no plotting) and writes RESULTS.md with a
header, one section per experiment E1-E6 (objective from Table 10, setup from
the manifest, the generated tables, figure links, the README observations), a
"Weak results" list, a README-vs-CSV table check (mismatches are reported,
not fixed) and a list of *proposed* headline figures.

    python scripts/week6_summary.py [--quick] [--root DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.week6 import config_hash, git_commit, read_rows, week6_config  # noqa: E402
from experiments.week6_common import check_readme_tables, fmt, week6_root, write_text  # noqa: E402

EXPERIMENTS = [
    ("E1", "e1_admm_scaling", "Evaluate ADMM scaling", "Hierarchical", "30/45/60/75 agents, no attack", "P2"),
    ("E2", "e2_formation", "Evaluate corridor merge success and throughput", "Hierarchical",
     "Three corridors with varying density", "P3"),
    ("E3", "e3_priority", "Evaluate priority compliance", "Hierarchical", "Emergency agent injected into traffic", "P4"),
    ("E4", "e4_resilience", "Compare resilience under attack", "Hierarchical / Centralized / Decentralized-undefended",
     "One agent falsifies position at t = 60 s", "P5"),
    ("E5", "e5_stl", "Evaluate STL robustness", "All evaluated architectures", "Same scenarios as E1–E4", "P6"),
    ("E6", "e6_degradation", "Evaluate graceful degradation", "Hierarchical", "Overseer communication link dropped",
     "P4 + P1"),
]

PROPOSED_FIGURES = [
    ("e4_main_comparison", "E4 headline: three architectures, attack off vs on (throughput, violations, recovery, "
                           "min robustness)"),
    ("e4_robustness_timeseries", "E4: robustness over time with the attack onset — the resilience story in one plot"),
    ("e1_iterations_vs_N", "E1: ADMM effort vs fleet size"),
    ("e1_convergence_vs_iteration_limit", "E1: convergence vs iteration limit"),
    ("e2_merge_success_vs_N", "E2: corridor merge success vs density"),
    ("e3_emergency_delay_vs_N", "E3: emergency-agent delay vs density"),
    ("e5_violation_fraction_vs_N", "E5: STL violating fraction per architecture vs N"),
    ("e6_directive_age_timeline", "E6: directive age through the overseer outage"),
]


def _section(text: str, heading: str) -> str:
    """Body of the '## <heading>' section of a README (up to the next '## ')."""
    m = re.search(rf"^## {re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", text, flags=re.S | re.M)
    return m.group(1).strip() if m else ""


def _sections_starting(text: str, prefix: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(rf"^## ({re.escape(prefix)}[^\n]*)\n(.*?)(?=^## |\Z)", text, flags=re.S | re.M):
        out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def _runs_count(d: Path) -> int:
    current = config_hash()
    return sum(1 for r in read_rows(d / "runs.csv") if r.get("base_config_hash") == current)


def build(root: Path) -> tuple[str, list[str]]:
    """Return (RESULTS.md text, table-check problems)."""
    w6 = week6_config()
    total_runs, total_wall = 0, 0.0
    sections, weak_all, problems, present = [], [], [], []
    for code, sub, objective, arch, scenario, owner in EXPERIMENTS:
        d = root / sub
        readme_p, man_p = d / "README.md", d / "manifest.json"
        if not readme_p.is_file() or not man_p.is_file():
            sections.append(f"## {code} — {objective}\n\n_Not available yet: {sub}/README.md or manifest.json "
                            "missing._\n")
            continue
        present.append(code)
        man = json.loads(man_p.read_text(encoding="utf-8"))
        readme = readme_p.read_text(encoding="utf-8")
        n_runs = _runs_count(d)
        total_runs += n_runs
        total_wall += float(man.get("wall_time_s") or 0.0)
        problems += [f"{code}: {p}" for p in check_readme_tables(readme_p)]
        results = _sections_starting(readme, "Results")
        figs = _section(readme, "Figures").replace("../figures/", "figures/")
        obs = _section(readme, "Observations")
        extra = _section(readme, "Outage behaviour (reported, not changed)") or \
            "\n".join(_section(readme, "Paired attack effect (on − off, same seed)").splitlines()[-4:]) \
            if code in ("E6", "E4") else ""
        body = [f"## {code} — {objective}", "",
                f"**Table 10:** {arch}; {scenario}; owner {owner}.  ",
                f"**Setup (manifest):** matrices {', '.join(man.get('matrices', []) or [str(man.get('matrix', ''))])};"
                f" seeds {man.get('seeds')}; N = {man.get('agent_counts')}; {n_runs} runs in runs.csv; "
                f"commit `{man.get('git_commit')}`; [README]({sub}/README.md)", ""]
        for title, content in results:
            body += [f"### {title}", "", content, ""]
        if extra:
            body += ["### Notes", "", extra, ""]
        body += ["### Figures", "", figs or "_none_", "", "### Observations", "", obs or "_none_", ""]
        sections.append("\n".join(body))
        wp = d / "weak_results.json"
        if wp.is_file():
            for g in json.loads(wp.read_text(encoding="utf-8")).get("weak_groups", []):
                key = ", ".join(f"{k}={v}" for k, v in g["group"].items())
                weak_all.append(f"- {code} ({key}): {'; '.join(g['reasons'])}")

    header = [
        "# MASooda — Week 6 results",
        "",
        "> **PROVISIONAL — pre-bug-fix results.**" if w6.get("provisional", True) else "",
        "",
        f"- Commit: `{git_commit()}`",
        f"- Config hash: `{config_hash()}`",
        f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"- Provisional: {bool(w6.get('provisional', True))}",
        f"- Experiments present: {', '.join(present) or 'none'}",
        f"- Total runs (current config): {total_runs}",
        f"- Total wall time recorded in the manifests: {fmt(total_wall / 60.0)} min "
        "(last invocation per folder; resumed runs are not re-timed)",
        "",
        "ADMM is reported as conflict *mitigation*; none of these numbers is a safety guarantee. Tables are copied "
        "from each experiment README, which generates them from its summary CSV (mean ± 95% CI half-width, n = runs "
        "with a value; n/a = not observed).",
        "",
    ]
    check = ["## README table check", ""]
    check += [f"- {p}" for p in problems] if problems else ["- Every README table matches its summary CSV."]
    weak = ["## Weak results", "", "Listed only; none was re-run (decision: do not re-run weak groups).", ""]
    weak += weak_all or ["- None."]
    prop = ["## Proposed headline figures (report and slides) — *proposed, please confirm*", ""]
    for name, why in PROPOSED_FIGURES:
        exists = (root / "figures" / f"{name}.png").is_file()
        prop.append(f"- [{name}](figures/{name}.png) — {why}{'' if exists else ' (figure not generated yet)'}")
    text = "\n".join(header) + "\n" + "\n".join(sections) + "\n" + "\n".join(weak) + "\n\n" + \
        "\n".join(check) + "\n\n" + "\n".join(prop) + "\n"
    return text, problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--root", default=None, help="outputs/week6 folder (default from config)")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else week6_root(args.quick)
    text, problems = build(root)
    write_text(root / "RESULTS.md", text)
    print(f"[summary] wrote {root / 'RESULTS.md'}; table mismatches: {len(problems)}")
    for p in problems:
        print(f"  - {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
