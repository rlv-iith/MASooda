"""Tests for scripts/week6_summary.py: RESULTS.md from two tiny fake experiment folders."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from experiments.week6 import config_hash, write_csv
from experiments.week6_common import md_summary_table, write_text

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SUMMARY = [
    {"num_agents": "30", "m_mean": "1.5", "m_std": "0.5", "m_n": "3", "m_ci_lo": "0.258", "m_ci_hi": "2.742"},
    {"num_agents": "60", "m_mean": "nan", "m_std": "nan", "m_n": "0", "m_ci_lo": "nan", "m_ci_hi": "nan"},
]


def _fake(root: Path, sub: str, tamper: bool = False, weak: list | None = None) -> None:
    d = root / sub
    d.mkdir(parents=True)
    cols = list(SUMMARY[0].keys())
    write_csv(SUMMARY, d / "summary.csv", cols)
    write_csv([{"spec_hash": "a", "base_config_hash": config_hash()},
               {"spec_hash": "b", "base_config_hash": "stale"}], d / "runs.csv", ["spec_hash", "base_config_hash"])
    table = md_summary_table(SUMMARY, ["num_agents"], ["m"])
    if tamper:
        table = table.replace("1.5 ±", "9.9 ±")
    write_text(d / "README.md", f"# {sub}\n\n## Setup\n- x\n\n## Results — main\n{table}\n\n"
                                f"## Figures\n- [f](../figures/f.png)\n\n## Observations\n- obs for {sub}\n")
    with open(d / "manifest.json", "w", encoding="utf-8") as f:
        json.dump({"matrices": [sub], "seeds": [42, 43, 44], "agent_counts": [30, 60], "wall_time_s": 120.0,
                   "git_commit": "abc"}, f)
    with open(d / "weak_results.json", "w", encoding="utf-8") as f:
        json.dump({"weak_groups": weak or []}, f)


def test_results_md_from_two_fake_folders(tmp_path):
    _fake(tmp_path, "e1_admm_scaling", weak=[{"group": {"num_agents": "60"}, "reasons": ["m: n=0 < 3"]}])
    _fake(tmp_path, "e2_formation", tamper=True)
    mod = _load("week6_summary")
    assert mod.main(["--root", str(tmp_path)]) == 0
    text = (tmp_path / "RESULTS.md").read_text(encoding="utf-8")
    assert "## E1 — Evaluate ADMM scaling" in text and "## E2 — Evaluate corridor merge" in text
    assert "_Not available yet" in text  # E3-E6 missing
    assert "Total runs (current config): 2" in text  # stale rows excluded
    assert "Total wall time recorded in the manifests: 4 min" in text
    assert "1.5 ± 1.2 (n=3)" in text and "n/a" in text
    assert "obs for e1_admm_scaling" in text
    assert "](figures/f.png)" in text
    assert "E1 (num_agents=60): m: n=0 < 3" in text
    assert "E2: e2_formation" not in text  # mismatch messages name the README file
    assert "README.md: table from summary.csv (m) does not match the CSV" in text
    assert "proposed, please confirm" in text
    _, problems = mod.build(tmp_path)
    assert len(problems) == 1 and problems[0].startswith("E2:")
