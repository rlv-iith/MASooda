"""Tests for scripts/run_all.py: stage selection, logging and the artifact checklist."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("run_all", ROOT / "scripts" / "run_all.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_all"] = mod  # dataclasses look their module up here
    spec.loader.exec_module(mod)
    return mod


RA = _load()


def test_only_selects_experiment_stages_and_keeps_common_ones():
    stages = RA.build_stages(quick=True)
    names = [s.name for s in RA.select_stages(stages, only=["e1", "e4"])]
    assert "env" in names and "summary" in names and "video" in names
    assert "smoke_centralized" in names
    assert {"run_e1", "plot_e1", "run_e4", "plot_e4"} <= set(names)
    assert not any(n.endswith(("e2", "e3", "e5", "e6")) for n in names)


def test_skip_video_and_unknown_experiment():
    stages = RA.build_stages(quick=True)
    assert "video" not in [s.name for s in RA.select_stages(stages, skip_video=True)]
    with pytest.raises(ValueError):
        RA.select_stages(stages, only=["e9"])


def test_flags_are_forwarded():
    stages = {s.name: s for s in RA.build_stages(quick=True, workers=3, fresh=True)}
    assert stages["run_e1"].cmd[-4:] == ["--quick", "--workers", "3", "--fresh"]
    assert "--run-missing" in stages["run_e5"].cmd
    assert "pytest" not in " ".join(" ".join(map(str, s.cmd)) for s in stages.values() if not callable(s.cmd))


def test_fake_stages_logging_and_artifact_checklist(tmp_path):
    made = tmp_path / "made.txt"
    stages = [
        RA.Stage("ok", [sys.executable, "-c", f"open(r'{made}', 'w').write('x'); print('hello')"], [made]),
        RA.Stage("fails", [sys.executable, "-c", "import sys; sys.exit(3)"], [tmp_path / "never.txt"]),
        RA.Stage("callable", lambda: 0),
    ]
    log = tmp_path / "run_all.log"
    res = RA.run_stages(stages, log, cwd=tmp_path, echo=lambda *_: None)
    assert [r["exit"] for r in res] == [0, 3, 0]
    text = log.read_text(encoding="utf-8")
    assert "hello" in text and "--- fails: exit 3" in text
    arts = RA.check_artifacts(stages)
    assert arts == [(made, True), (tmp_path / "never.txt", False)]
