"""The memoized path resolution in config/load_config.py keeps load_config's behaviour.

Bit-identical simulation output with the change is covered by
tests/test_week6_harness.py::test_runner_defaults_bit_identical_to_pre_week6_golden.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

import config.load_config  # noqa: F401  (module object below)

lc = sys.modules["config.load_config"]


def test_default_config_is_cached_object():
    assert lc.get_config() is lc.get_config()
    assert lc.load_config() is lc.get_config()


def test_explicit_absolute_and_relative_paths(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("a: 1\n", encoding="utf-8")
    assert lc.load_config(p) == {"a": 1}
    p.write_text("a: 2\n", encoding="utf-8")
    assert lc.load_config(p) == {"a": 1}             # cached
    assert lc.load_config(p, reload=True) == {"a": 2}  # reload re-reads
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        assert lc.load_config(Path("c.yaml")) == {"a": 2}  # relative path resolved against cwd
    finally:
        os.chdir(cwd)


def test_resolution_is_memoized_for_absolute_paths():
    key1 = lc._resolved_key(lc.DEFAULT_CONFIG_PATH)
    assert lc.DEFAULT_CONFIG_PATH in lc._RESOLVED_PATHS
    assert key1 == str(lc.DEFAULT_CONFIG_PATH.resolve())
