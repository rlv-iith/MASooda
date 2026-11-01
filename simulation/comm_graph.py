"""Communication graph construction algorithms.

Provides radius-based and k-nearest-neighbor communication graph builders
operating in 2D (x, y) coordinates.
"""

from __future__ import annotations

from typing import Sequence
import numpy as np

from .schema import AgentState, CommunicationGraph


def build_radius_graph(
    agents: Sequence[AgentState],
    radius: float,
) -> CommunicationGraph:
    """Construct an undirected communication graph where agents within radius are neighbors.

    Parameters
    ----------
    agents : Sequence[AgentState]
        Sequence of agent states.
    radius : float
        Communication radius in meters (evaluated only in x and y coordinates).

    Returns
    -------
    CommunicationGraph
        Communication graph with adjacency mapping agent_id -> list of neighbor IDs.
    """
    if not agents:
        return CommunicationGraph(adjacency={})

    adj: dict[int, list[int]] = {agent.id: [] for agent in agents}
    n = len(agents)

    for i in range(n):
        ai = agents[i]
        pi = ai.position[:2]
        for j in range(i + 1, n):
            aj = agents[j]
            pj = aj.position[:2]
            dist = float(np.hypot(pi[0] - pj[0], pi[1] - pj[1]))
            if dist <= radius:
                adj[ai.id].append(aj.id)
                adj[aj.id].append(ai.id)

    for aid in adj:
        adj[aid].sort()

    return CommunicationGraph(adjacency=adj)


def build_knn_graph(
    agents: Sequence[AgentState],
    k: int,
) -> CommunicationGraph:
    """Construct a communication graph where each agent links to its k nearest neighbors.

    Symmetric closure is applied: if agent i links to agent j, then j also links to i.

    Parameters
    ----------
    agents : Sequence[AgentState]
        Sequence of agent states.
    k : int
        Number of nearest neighbors to connect to.

    Returns
    -------
    CommunicationGraph
        Symmetric communication graph with adjacency mapping agent_id -> list of neighbor IDs.
    """
    if not agents:
        return CommunicationGraph(adjacency={})

    adj: dict[int, list[int]] = {agent.id: [] for agent in agents}
    if k <= 0 or len(agents) <= 1:
        return CommunicationGraph(adjacency=adj)

    directed_edges: set[tuple[int, int]] = set()
    n = len(agents)

    for i in range(n):
        ai = agents[i]
        pi = ai.position[:2]
        candidates: list[tuple[float, int]] = []
        for j in range(n):
            if i == j:
                continue
            aj = agents[j]
            pj = aj.position[:2]
            dist = float(np.hypot(pi[0] - pj[0], pi[1] - pj[1]))
            candidates.append((dist, aj.id))

        # Sort primarily by distance, break ties by agent id
        candidates.sort(key=lambda item: (item[0], item[1]))
        num_links = min(k, len(candidates))
        for dist, neighbor_id in candidates[:num_links]:
            directed_edges.add((ai.id, neighbor_id))

    # Apply symmetric closure: if i links to j then j links to i
    for u, v in directed_edges:
        adj[u].append(v)
        adj[v].append(u)

    for aid in adj:
        adj[aid] = sorted(list(set(adj[aid])))

    return CommunicationGraph(adjacency=adj)

