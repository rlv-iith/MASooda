from __future__ import annotations

from config.load_config import get_config
from simulation import interfaces


class OverseerLink:
    def __init__(self, link_config: dict | None = None) -> None:
        if link_config is None:
            link_config = get_config().get("overseer", {}).get("link_failure", {})

        self.enabled = bool(link_config.get("enabled", False))
        self.down_start = float(link_config.get("down_start_seconds", 0.0))
        self.down_end = float(link_config.get("down_end_seconds", 0.0))
        self.calls = 0
        self.dropped = 0
        self.errors = 0

    def is_up(self, t: float) -> bool:
        if not self.enabled:
            return True
        return not (self.down_start <= t < self.down_end)

    def request(self, snapshot, t: float):
        self.calls += 1
        if not self.is_up(t):
            self.dropped += 1
            return None

        try:
            return interfaces.overseer_update(snapshot)
        except Exception:
            self.errors += 1
            return None
