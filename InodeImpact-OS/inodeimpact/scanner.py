"""Read-only bounded file-system walk and evidence-based dependency extraction.

No directory symlinks are traversed. An edge A -> B means A depends on B.
References are heuristic, not a substitute for language-aware build tooling.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat

from .models import Edge, Node, Snapshot

MAX_FILES = 4000
MAX_FILE_BYTES = 768 * 1024
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".runtime", "dist", "build"}
TEXT_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".htm", ".css", ".md", ".json", ".yaml", ".yml", ".txt", ".toml", ".xml", ".sh", ".ini", ".cfg", ".csv"}
# Regexes recognize text references; matched targets must exist in the snapshot.
WEB_REF = re.compile(r'''(?:src|href|url\(|import\s*(?:\(|(?:[^;\n]+?from\s*))|require\(|fetch\()\s*["'(\s]*([\w./@+-]+\.[A-Za-z0-9]+)''', re.I)
MD_REF = re.compile(r'''!?\[[^\]]*\]\(([^\s)#?]+)(?:[?#][^)]*)?\)''')
QUOTED_REF = re.compile(r'''["']([^"'\n]{1,180}\.(?:py|js|ts|jsx|tsx|json|yaml|yml|html|htm|css|md|txt|csv|svg|png|jpg|jpeg|webp|xml|toml|pdf))(?:[?#][^"']*)?["']''', re.I)


def _make_node(base: Path, absolute: Path, st: os.stat_result) -> Node:
    relative = absolute.relative_to(base).as_posix()
    mode = stat.filemode(st.st_mode)
    kind = "symlink" if stat.S_ISLNK(st.st_mode) else ("directory" if stat.S_ISDIR(st.st_mode) else "file" if stat.S_ISREG(st.st_mode) else "special")
    digest = ""
    if kind == "file" and st.st_size <= MAX_FILE_BYTES:
        try:
            h = hashlib.sha256()
            with absolute.open("rb") as stream:
                for block in iter(lambda: stream.read(65536), b""):
                    h.update(block)
            digest = h.hexdigest()
        except (OSError, PermissionError):
            pass
    link_target = ""
    if kind == "symlink":
        try:
            link_target = os.readlink(absolute)
        except OSError:
            pass
    return Node(relative, kind, st.st_size if kind == "file" else 0, int(st.st_ino), int(st.st_dev), int(st.st_nlink), st.st_mtime, mode, absolute.suffix.lower(), digest, link_target)


def _match_existing(source: str, reference: str, paths: set[str]) -> str | None:
    """Map a referenced path to a path within the scanned tree only."""
    reference = reference.strip().split("?", 1)[0].split("#", 1)[0].replace("\\", "/")
    if not reference or "://" in reference or reference.startswith(("data:", "mailto:", "#", "//")):
        return None
    source_parent = PurePosixPath(source).parent
    candidates = [PurePosixPath(reference.lstrip("/"))] if reference.startswith("/") else [source_parent / reference, PurePosixPath(reference)]
    for candidate in candidates:
        parts: list[str] = []
        for part in candidate.parts:
            if part == "..":
                if parts:
                    parts.pop()
                else:
                    break
            elif part not in (".", ""):
                parts.append(part)
        else:
            path = "/".join(parts)
            if path in paths and path != source:
                return path
    return None


def _python_import_edges(source: str, text: str, paths: set[str]) -> list[Edge]:
    try:
        tree = ast.parse(text, filename=source)
    except SyntaxError:
        return []
    output: list[Edge] = []
    parent = PurePosixPath(source).parent
    for item in ast.walk(tree):
        if isinstance(item, ast.Import):
            names = [(alias.name, 0) for alias in item.names]
        elif isinstance(item, ast.ImportFrom):
            names = [(item.module or "", item.level)]
            if item.module:
                names += [(f"{item.module}.{alias.name}", item.level) for alias in item.names if alias.name != "*"]
            else:
                names += [(alias.name, item.level) for alias in item.names if alias.name != "*"]
        else:
            continue
        for module, level in names:
            base = parent
            if level:
                for _ in range(level - 1):
                    base = base.parent
            else:
                base = PurePosixPath(".")
            module_path = module.replace(".", "/")
            for prefix in ([base] if level else [PurePosixPath("."), parent]):
                rel = str(prefix / module_path).lstrip("./")
                for candidate in (f"{rel}.py", f"{rel}/__init__.py"):
                    if candidate in paths and candidate != source:
                        output.append(Edge(source, candidate, "python-import", module))
                        break
                else:
                    continue
                break
    return output


def scan(root: str | Path, max_nodes: int = MAX_FILES) -> Snapshot:
    """Scan a tree without modifying it, reading only small known text files."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Folder does not exist: {root}")
    nodes: dict[str, Node] = {}
    warnings: list[str] = []
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            with os.scandir(folder) as entries:
                children = sorted(list(entries), key=lambda e: e.name.lower())
        except OSError as exc:
            warnings.append(f"Cannot read {folder.relative_to(root)}: {exc.strerror}")
            continue
        for entry in children:
            if entry.name in SKIP_DIRS and entry.is_dir(follow_symlinks=False):
                continue
            if len(nodes) >= max_nodes:
                warnings.append(f"Scan limited to {max_nodes} nodes; results may be incomplete")
                stack.clear()
                break
            absolute = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
                node = _make_node(root, absolute, info)
                nodes[node.path] = node
                if node.kind == "directory":
                    stack.append(absolute)
            except OSError as exc:
                warnings.append(f"Skipped {entry.name}: {exc.strerror}")
    paths = set(nodes)
    edges: list[Edge] = []
    seen: set[tuple[str, str, str]] = set()

    def record(edge: Edge) -> None:
        key = (edge.source, edge.target, edge.reason)
        if key not in seen:
            seen.add(key)
            edges.append(edge)

    for source, node in nodes.items():
        if node.kind == "symlink":
            target = _match_existing(source, node.link_target, paths)
            if target:
                record(Edge(source, target, "symbolic-link", node.link_target))
            continue
        if node.kind != "file" or node.extension not in TEXT_EXT or node.size > MAX_FILE_BYTES:
            continue
        try:
            text = (root / source).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if node.extension == ".py":
            for edge in _python_import_edges(source, text, paths):
                record(edge)
        for pattern, reason in ((WEB_REF, "web-reference"), (MD_REF, "document-link"), (QUOTED_REF, "path-reference")):
            for match in pattern.finditer(text):
                reference = match.group(1)
                target = _match_existing(source, reference, paths)
                if target:
                    record(Edge(source, target, reason, reference[:120]))
    edges.sort(key=lambda e: (e.source, e.target, e.reason))
    return Snapshot(str(root), nodes, edges, datetime.now(timezone.utc).isoformat(timespec="seconds"), warnings)
