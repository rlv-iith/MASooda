"""Decentralized-undefended architecture (workflow Section 13.5, experiment E4)."""

from __future__ import annotations

from simulation.engine import SimulationResult, run_simulation


def run_decentralized_undefended(
    agents,
    duration_s: float | None = None,
    loggers: list | None = None,
    attack_config: dict | None = None,
    overseer_link_config: dict | None = None,
    telemetry: object | None = None,
) -> SimulationResult:
    """Run the fleet with local boids and ADMM but no overseer and no defence.

    Honest agents use the raw, possibly falsified, neighbour reports directly in
    their averaging-based boids terms (the plain-averaging baseline from Week 2).
    Nothing is filtered: no W-MSR and no range check, so a lying neighbour pulls
    its honest neighbours off course. Conflicts are still resolved between
    neighbours with ADMM. There is no central overseer, so agents keep the
    corridor they start with and are never re-assigned.

    ``overseer_link_config`` is accepted only so every architecture shares one
    signature; it is ignored because there is no overseer link to fail.
    ``telemetry`` (optional, Week 6) is passed through to ``run_simulation``.
    """
    return run_simulation(
        agents,
        duration_s=duration_s,
        loggers=loggers,
        use_overseer=False,
        use_admm=True,
        attack_config=attack_config,
        defended=False,
        overseer_link_config={"enabled": False},
        telemetry=telemetry,
    )
