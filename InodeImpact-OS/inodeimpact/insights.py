"""Explainable dependency topology metrics for a single read-only snapshot.

The centrality index is a prioritization aid, not a failure probability.
No external data, network calls, or file modifications are involved.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .models import Snapshot


def _cycles(graph: dict[str, set[str]], max_results: int = 20) -> list[list[str]]:
    """Identify strongly connected dependency components using Tarjan's algorithm."""
    index = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    result: list[list[str]] = []

    # Iterative DFS avoids recursion depth issues on deeply nested import chains.
    for root in sorted(graph):
        if root in indices:
            continue
        frames: list[tuple[str, object, str | None]] = [(root, iter(sorted(graph[root])), None)]
        while frames:
            node, neighbors, parent = frames[-1]
            if node not in indices:
                indices[node] = lowlink[node] = index
                index += 1
                stack.append(node)
                on_stack.add(node)
            try:
                neighbor = next(neighbors)
            except StopIteration:
                frames.pop()
                if parent is not None:
                    lowlink[parent] = min(lowlink[parent], lowlink[node])
                if lowlink[node] == indices[node]:
                    component = []
                    while True:
                        member = stack.pop()
                        on_stack.remove(member)
                        component.append(member)
                        if member == node:
                            break
                    if len(component) > 1 or node in graph[node]:
                        result.append(sorted(component))
                continue
            if neighbor not in indices:
                frames.append((neighbor, iter(sorted(graph[neighbor])), node))
            elif neighbor in on_stack:
                lowlink[node] = min(lowlink[node], indices[neighbor])
    result.sort(key=lambda group: (-len(group), group))
    return result[:max_results]


def compute_insights(snapshot: Snapshot, limit: int = 12) -> dict[str, Any]:
    """Rank critical resources and surface graph anomalies with bounded output."""
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    nodes = snapshot.nodes
    consumers: dict[str, set[str]] = {path: set() for path in nodes}
    dependencies: dict[str, set[str]] = {path: set() for path in nodes}
    for edge in snapshot.edges:
        if edge.source in nodes and edge.target in nodes:
            consumers[edge.target].add(edge.source)
            dependencies[edge.source].add(edge.target)

    ranking = []
    for path, direct in consumers.items():
        if not direct:
            continue
        visited: set[str] = set()
        queue = deque(sorted(direct))
        while queue:
            current = queue.popleft()
            if current in visited or current == path:
                continue
            visited.add(current)
            for other in sorted(consumers[current]):
                if other not in visited and other != path:
                    queue.append(other)
        transitive = len(visited - direct)
        # Distinct consumers, not raw edges, are used to avoid duplicate-reference bias.
        index = min(100, 10 * len(direct) + 3 * transitive)
        ranking.append({
            "path": path, "kind": nodes[path].kind,
            "direct_consumers": len(direct), "transitive_consumers": transitive,
            "total_consumers": len(visited), "centrality_index": index,
            "sample_consumers": sorted(direct)[:4],
        })
    ranking.sort(key=lambda item: (-item["total_consumers"], -item["direct_consumers"], item["path"]))

    link_groups: dict[tuple[int, int], list[str]] = defaultdict(list)
    for n in nodes.values():
        if n.kind == "file" and n.links > 1 and n.inode:
            link_groups[(n.device, n.inode)].append(n.path)
    hardlinks = [sorted(paths) for paths in link_groups.values() if len(paths) > 1]
    hardlinks.sort(key=lambda group: (-len(group), group))
    isolated = sorted(p for p, n in nodes.items() if n.kind == "file" and not consumers[p] and not dependencies[p])
    return {
        "root": snapshot.root,
        "snapshot_id": snapshot.snapshot_id,
        "scanned_at": snapshot.scanned_at,
        "summary": {
            "resources_with_consumers": sum(bool(v) for v in consumers.values()),
            "isolated_files": len(isolated),
            "cyclic_groups": len(_cycles(dependencies, max_results=len(nodes))),
            "hardlink_groups": len(hardlinks),
            "warnings": len(snapshot.warnings),
        },
        "hotspots": ranking[:limit],
        "cycles": _cycles(dependencies),
        "hardlinks": hardlinks[:20],
        "isolated_file_examples": isolated[:limit],
        "method": "Reverse-dependency reachability; centrality index is heuristic, not a probability.",
        "limitations": "Static references only; generated paths, runtime loading and external consumers may be missing.",
    }
