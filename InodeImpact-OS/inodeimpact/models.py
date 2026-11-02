"""Small, serializable structures used by the scanner, analysis engine and API."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Node:
    path: str
    kind: str
    size: int
    inode: int
    device: int
    links: int
    modified: float
    mode: str
    extension: str = ""
    sha256: str = ""
    link_target: str = ""

    def json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    reason: str
    evidence: str

    def json(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class Snapshot:
    root: str
    nodes: dict[str, Node]
    edges: list[Edge]
    scanned_at: str
    warnings: list[str] = field(default_factory=list)
    snapshot_id: int | None = None

    def json(self) -> dict[str, Any]:
        files = [n for n in self.nodes.values() if n.kind == "file"]
        return {
            "snapshot_id": self.snapshot_id,
            "root": self.root,
            "scanned_at": self.scanned_at,
            "summary": {
                "nodes": len(self.nodes),
                "files": len(files),
                "folders": sum(n.kind == "directory" for n in self.nodes.values()),
                "symlinks": sum(n.kind == "symlink" for n in self.nodes.values()),
                "dependencies": len(self.edges),
                "bytes": sum(n.size for n in files),
                "orphan_files": sum(not any(e.target == n.path for e in self.edges) for n in files),
            },
            "nodes": [n.json() for n in sorted(self.nodes.values(), key=lambda x: x.path)],
            "edges": [e.json() for e in self.edges],
            "warnings": self.warnings,
        }
