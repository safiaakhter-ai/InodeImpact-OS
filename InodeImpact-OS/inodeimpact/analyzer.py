"""Deterministic preflight: predict consumers affected by a file operation."""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import PurePosixPath
from typing import Any

from .models import Snapshot

VALID_OPERATIONS = {"delete", "move", "copy", "modify"}


def normalize_relative(value: str) -> str:
    """Reject absolute/traversal paths before accessing the managed workspace."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A relative file path is required")
    value = value.strip().replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("..", ".runtime", ".git") for p in path.parts) or ":" in value:
        raise ValueError("Only safe relative paths within the workspace are allowed")
    normalized = path.as_posix()
    if normalized in (".", ""):
        raise ValueError("Cannot operate on the workspace root")
    return normalized


def analyze(snapshot: Snapshot, operation: str, source: str, destination: str = "") -> dict[str, Any]:
    operation = operation.strip().lower()
    if operation not in VALID_OPERATIONS:
        raise ValueError("Operation must be delete, move, copy, or modify")
    source = normalize_relative(source)
    destination = normalize_relative(destination) if operation in {"move", "copy"} else ""
    if source not in snapshot.nodes:
        raise ValueError(f"Source not found in current snapshot: {source}")
    if destination and (destination == source or destination in snapshot.nodes):
        raise ValueError("Destination must be different and must not exist already")
    if destination and snapshot.nodes[source].kind == "directory" and destination.startswith(source + "/"):
        raise ValueError("A folder cannot be moved or copied inside itself")
    if destination and any(p in snapshot.nodes and snapshot.nodes[p].kind != "directory" for p in _parents(destination)):
        raise ValueError("Destination has a parent path that is not a directory")

    included = {p for p in snapshot.nodes if p == source or p.startswith(source + "/")}
    reverse: dict[str, set[str]] = defaultdict(set)
    for edge in snapshot.edges:
        reverse[edge.target].add(edge.source)
    direct = {ref for path in included for ref in reverse[path] if ref not in included}
    levels: dict[str, int] = {}
    next_hop: dict[str, str] = {}
    queue = deque((ref, 1) for ref in sorted(direct))
    for ref in sorted(direct):
        possible = sorted(p for p in included if ref in reverse[p])
        if possible:
            next_hop[ref] = possible[0]
    while queue:
        path, distance = queue.popleft()
        if path in included or (path in levels and levels[path] <= distance):
            continue
        levels[path] = distance
        if len(levels) >= 2000:
            break
        for parent in sorted(reverse[path]):
            if parent not in included and parent not in levels and parent not in next_hop:
                next_hop[parent] = path
                queue.append((parent, distance + 1))
    transitive = set(levels) - direct
    incoming_edges = [e.json() for e in snapshot.edges if e.target in included and e.source not in included]
    outgoing_edges = [e.json() for e in snapshot.edges if e.source in included and e.target not in included]
    broken = operation in {"delete", "move"}
    affected = (direct | transitive) if broken else set()
    if operation == "modify":
        affected = direct | transitive
    size = sum(snapshot.nodes[p].size for p in included if snapshot.nodes[p].kind == "file")
    hardlinks = [p for p in included if snapshot.nodes[p].kind == "file" and snapshot.nodes[p].links > 1]
    external_refs = len(incoming_edges)
    factors = {
        "operation_baseline": {"delete": 18, "move": 13, "modify": 13, "copy": 2}[operation],
        "direct_consumers": min(43, len(direct) * 17) if operation != "copy" else 0,
        "indirect_consumers": min(22, len(transitive) * 7) if operation != "copy" else 0,
        "duplicate_references": min(10, max(0, external_refs - len(direct)) * 3) if operation != "copy" else 0,
        "subtree_scope": min(12, 3 + len(included) // 4) if len(included) > 1 and operation in {"delete", "move"} else 0,
        "moved_outgoing_links": min(12, len(outgoing_edges) * 3) if operation == "move" else 0,
    }
    score = min(100, sum(factors.values()))
    risk = "CRITICAL" if score >= 75 else "HIGH" if score >= 50 else "MODERATE" if score >= 25 else "LOW"

    notes: list[str] = []
    if incoming_edges and broken:
        notes.append(f"{len(incoming_edges)} reference(s) to the selected path(s) may break")
    if operation == "modify" and incoming_edges:
        notes.append("Consumers may change behavior if the file's content or interface changes")
    if operation == "move" and outgoing_edges:
        notes.append("Relative references inside moved files may need rewriting")
    if hardlinks:
        notes.append(f"{len(hardlinks)} file(s) have multiple hard links; deleting one pathname may not release its inode data")
    if snapshot.warnings:
        notes.append("The scan was incomplete or contained unreadable paths; risk may be underestimated")
    if operation == "copy":
        notes.append("Copying keeps original references intact; the new copy is not automatically referenced")
    if not notes:
        notes.append("No static dependencies were detected; runtime or external consumers may still exist")

    # An explainable shortest dependency chain per affected consumer.
    evidence = {}
    for edge in snapshot.edges:
        key = (edge.source, edge.target)
        if key not in evidence:
            evidence[key] = {"reason": edge.reason, "evidence": edge.evidence}
    dependency_paths = []
    if operation != "copy":
        for consumer in sorted(affected, key=lambda p: (levels.get(p, 9999), p))[:40]:
            chain = [consumer]
            seen_paths = {consumer}
            steps = []
            while chain[-1] not in included and chain[-1] in next_hop:
                current = chain[-1]
                target = next_hop[current]
                if target in seen_paths:
                    break
                steps.append({"source": current, "target": target, **evidence.get((current, target), {"reason": "dependency", "evidence": ""})})
                chain.append(target)
                seen_paths.add(target)
            if chain[-1] in included:
                dependency_paths.append({"consumer": consumer, "depth": len(steps), "chain": chain, "evidence": steps})

    recommendations = []
    if incoming_edges and operation in {"delete", "move"}:
        recommendations.append("Update or redirect the listed dependent paths before applying")
    if operation == "modify":
        recommendations.append("Validate downstream behavior with tests after making the change")
    if operation == "move":
        recommendations.append("Check imports, links and relative resource paths after moving")
    if operation == "delete":
        recommendations.append("Retain a recoverable backup until downstream checks pass")
    if operation == "copy":
        recommendations.append("Review duplicated content and ownership before treating the copy as independent")
    recommendations.append("Run a fresh scan to verify the post-operation dependency graph")

    return {
        "operation": operation, "source": source, "destination": destination,
        "risk_score": score, "risk_level": risk,
        "files_in_scope": len(included), "bytes_in_scope": size,
        "direct_dependents": sorted(direct),
        "transitive_dependents": sorted(transitive),
        "affected": sorted(affected),
        "incoming_edges": incoming_edges[:150],
        "outgoing_edges": outgoing_edges[:150],
        "impact_levels": {path: levels[path] for path in sorted(levels)},
        "dependency_paths": dependency_paths, "risk_factors": factors,
        "notes": notes, "recommendations": recommendations,
        "destructive": operation == "delete",
        "can_apply": True,  # The server separately enforces the managed-sandbox boundary.
        "confidence": "Static heuristic: imports, paths, documents and symlinks only",
    }


def _parents(path: str) -> list[str]:
    result = []
    p = PurePosixPath(path).parent
    while str(p) != ".":
        result.append(p.as_posix())
        p = p.parent
    return result
