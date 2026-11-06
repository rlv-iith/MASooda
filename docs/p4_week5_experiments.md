# P4 Week 5: E3 (emergency priority) and E6 (graceful degradation)

## Definitions

- **Priority-compliance rate**: every overseer update period (2 s) the emergency
  agent is checked; it is compliant if it has a corridor assignment and that
  corridor holds at most `corridors.capacity` (15) assigned agents. Rate =
  compliant checks / checks.
- **Emergency delay**: emergency travel time to the exit zone minus the nominal
  free-flow time `(exit_x - x0) / v_cruise`.
- **Imposed delay**: mean over the other agents that arrived in both runs of
  (travel time in the emergency run - travel time in the control run). In the
  control run the same agent is an ordinary DELIVERY agent.
- **Graceful degradation score**: safety violation ticks with the overseer link
  down divided by violation ticks with the link up (1.0 = no degradation).

## E3: one emergency agent injected into traffic

Means over seeds 42-44, 180 s, attack off.

| N | Compliance rate | Emergency delay (s) | Time saved vs control (s) | Imposed delay (s) | Violation ticks |
|---|---|---|---|---|---|
| 30 | 1.00 | 8.74 | 22.5 | -0.15 | 654 |
| 45 | 0.01 | 8.74 | 9.95 | 0.59 | 752 |
| 60 | 0.00 | 8.74 | 35.63 | 1.81 | 1744 |
| 75 | 0.00 | 8.74 | 11.4 | -0.53 | 1778 |

The emergency delay is identical across N because the same three agents are
selected at every density (seeds 42-44), and one control run at N=45 seed 44
had no arrival (NaN, ignored in the means).

## E6: overseer link down 90-120 s, 60 agents

| Seed | Violations normal | Violations failure | Score | Throughput normal / failure (1/s) | Max directive staleness (s) |
|---|---|---|---|---|---|
| 42 | 1774 | 1774 | 1.0 | 0.333 / 0.333 | 31.9 |
| 43 | 1776 | 1776 | 1.0 | 0.289 / 0.289 | 31.9 |
| 44 | 1782 | 1782 | 1.0 | 0.333 / 0.333 | 31.9 |

## Findings

The emergency agent crosses the corridor 5 s later than free flow on average and
saves 10-36 s compared with being an ordinary agent, but it reaches that
position only at the cost of corridor load: compliance is 1.0 at 30 agents and
collapses to about 0 from 45 agents, because its assigned corridor holds more
than 15 agents at the higher densities. The delay imposed on lower-priority
traffic is within about +/-2 s with no clear trend and is noisy at three seeds.
In E6 the link outage changed nothing: violations, throughput and score are
identical with and without failure, and `overseer_failures` is 0 even though
directive staleness reached 31.9 s. The outage therefore appears to have no
effect on trajectories in this configuration (agents follow cached or static
corridor assignments), so E6 does not yet show graceful degradation under a
disruptive failure; the high violation counts (~1780) at 60 agents are present
in both runs and are not caused by the link. This should be checked before the
E6 result is quoted.
