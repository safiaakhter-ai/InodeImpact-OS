"""Local SQLite history, change tracking and audit trail."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .models import Snapshot


class Store:
    def __init__(self, database: str | Path):
        database = Path(database)
        database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(database), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                root TEXT NOT NULL, scanned_at TEXT NOT NULL,
                nodes INTEGER NOT NULL, edges INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL, action TEXT NOT NULL,
                source TEXT NOT NULL, destination TEXT NOT NULL,
                risk TEXT NOT NULL, details TEXT NOT NULL
            );
        """)
        self.connection.commit()

    def save(self, snapshot: Snapshot) -> int:
        payload = snapshot.json()
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO snapshots(root,scanned_at,nodes,edges,data) VALUES (?,?,?,?,?)",
                (snapshot.root, snapshot.scanned_at, len(snapshot.nodes), len(snapshot.edges), json.dumps(payload)),
            )
        snapshot.snapshot_id = int(cursor.lastrowid)
        return snapshot.snapshot_id

    def history(self, root: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        sql = "SELECT id,root,scanned_at,nodes,edges FROM snapshots"
        params: tuple = ()
        if root:
            sql += " WHERE root=?"
            params = (root,)
        sql += " ORDER BY id DESC LIMIT ?"
        rows = self.connection.execute(sql, params + (min(limit, 100),)).fetchall()
        return [dict(row) for row in rows]

    def read_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT data FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def compare(self, old_id: int, new_id: int) -> dict[str, Any]:
        old = self.read_snapshot(old_id)
        new = self.read_snapshot(new_id)
        if old is None or new is None:
            raise ValueError("Snapshot not found")
        if old["root"] != new["root"]:
            raise ValueError("Can only compare snapshots of the same folder")
        a = {node["path"]: node for node in old["nodes"]}
        b = {node["path"]: node for node in new["nodes"]}
        added = sorted(set(b) - set(a))
        removed = sorted(set(a) - set(b))
        changed = sorted(p for p in set(a) & set(b) if any(a[p][key] != b[p][key] for key in ("sha256", "size", "kind", "link_target", "mode")))
        edge_key = lambda e: (e["source"], e["target"], e["reason"])
        edges_a = {edge_key(edge) for edge in old["edges"]}
        edges_b = {edge_key(edge) for edge in new["edges"]}
        return {
            "old_id": old_id, "new_id": new_id,
            "added": added, "removed": removed, "changed": changed,
            "new_edges": len(edges_b - edges_a), "removed_edges": len(edges_a - edges_b),
        }

    def audit(self, action: str, source: str, destination: str, risk: str, details: dict) -> int:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.connection:
            cur = self.connection.execute(
                "INSERT INTO audits(created_at,action,source,destination,risk,details) VALUES (?,?,?,?,?,?)",
                (timestamp, action, source, destination, risk, json.dumps(details)),
            )
        return int(cur.lastrowid)

    def audits(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM audits ORDER BY id DESC LIMIT ?", (min(limit, 100),)).fetchall()
        return [{**dict(row), "details": json.loads(row["details"])} for row in rows]

    def was_undone(self, audit_id: int) -> bool:
        rows = self.connection.execute("SELECT details FROM audits WHERE action='undo'").fetchall()
        return any(json.loads(row[0]).get("undo_of") == audit_id for row in rows)

    def get_audit(self, audit_id: int) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM audits WHERE id=?", (audit_id,)).fetchone()
        return {**dict(row), "details": json.loads(row["details"])} if row else None
