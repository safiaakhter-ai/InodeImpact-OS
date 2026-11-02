"""Run from project root: python -m unittest discover -s tests -v"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from inodeimpact.analyzer import analyze, normalize_relative
from inodeimpact.sandbox import Sandbox, seed_demo
from inodeimpact.scanner import scan
from inodeimpact.storage import Store


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.workspace = self.base / "demo_workspace"
        seed_demo(self.workspace)
        self.snapshot = scan(self.workspace)

    def test_seed_has_expected_files_and_edges(self):
        self.assertEqual(len([n for n in self.snapshot.nodes.values() if n.kind == "file"]), 20)
        self.assertGreaterEqual(len(self.snapshot.edges), 20)
        self.assertIn("config/settings.json", self.snapshot.nodes)

    def test_detects_python_import_chain(self):
        self.assertTrue(any(e.source == "app/main.py" and e.target == "app/core/report.py" and e.reason == "python-import" for e in self.snapshot.edges))
        self.assertTrue(any(e.source == "app/core/report.py" and e.target == "app/core/metrics.py" for e in self.snapshot.edges))

    def test_detects_web_assets_and_markdown_links(self):
        self.assertTrue(any(e.source == "website/index.html" and e.target == "website/styles.css" for e in self.snapshot.edges))
        self.assertTrue(any(e.source == "README.md" and e.target == "config/settings.json" for e in self.snapshot.edges))

    def test_path_reference_is_not_network_access(self):
        self.assertTrue(any(e.source == "website/dashboard.js" and e.target == "config/settings.json" for e in self.snapshot.edges))

    def test_config_delete_has_downstream_impact(self):
        result = analyze(self.snapshot, "delete", "config/settings.json")
        self.assertEqual(result["risk_level"], "HIGH")
        self.assertIn("app/main.py", result["direct_dependents"])
        self.assertIn("website/index.html", result["transitive_dependents"])
        self.assertGreaterEqual(len(result["affected"]), 7)

    def test_orphan_file_has_lower_delete_risk(self):
        result = analyze(self.snapshot, "delete", "archive/old-report.md")
        self.assertEqual(result["risk_level"], "LOW")
        self.assertEqual(result["affected"], [])

    def test_copy_does_not_break_original_references(self):
        result = analyze(self.snapshot, "copy", "config/settings.json", "config/settings-copy.json")
        self.assertEqual(result["risk_level"], "LOW")
        self.assertEqual(result["affected"], [])

    def test_move_needs_new_destination(self):
        with self.assertRaises(ValueError):
            analyze(self.snapshot, "move", "config/settings.json", "reports/template.md")
        with self.assertRaises(ValueError):
            analyze(self.snapshot, "move", "app", "app/deep")

    def test_traversal_and_absolute_rejected(self):
        for path in ("../outside", "/etc/passwd", "safe/../../escape", "C:\\Temp\\file", "", "."):
            with self.subTest(path=path), self.assertRaises(ValueError):
                normalize_relative(path)

    def test_scan_never_follows_folder_symlinks(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret", encoding="utf-8")
        link = self.workspace / "external"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Host does not permit symlink creation")
        snapshot = scan(self.workspace)
        self.assertIn("external", snapshot.nodes)
        self.assertNotIn("external/secret.txt", snapshot.nodes)

    def test_snapshot_diff(self):
        store = Store(self.base / "state.sqlite3")
        old = store.save(self.snapshot)
        (self.workspace / "archive" / "new-report.md").write_text("new", encoding="utf-8")
        (self.workspace / "archive" / "old-report.md").write_text("updated", encoding="utf-8")
        new = store.save(scan(self.workspace))
        result = store.compare(old, new)
        self.assertIn("archive/new-report.md", result["added"])
        self.assertIn("archive/old-report.md", result["changed"])

    def test_sandbox_delete_undo(self):
        store = Store(self.base / "db" / "state.sqlite3")
        sandbox = Sandbox(self.workspace, self.base / "backups", store)
        plan = analyze(self.snapshot, "delete", "config/settings.json")
        audit = sandbox.apply(plan)
        self.assertFalse((self.workspace / "config/settings.json").exists())
        sandbox.undo(audit)
        self.assertTrue((self.workspace / "config/settings.json").exists())
        with self.assertRaises(ValueError):
            sandbox.undo(audit)

    def test_sandbox_move_copy_modify_undo(self):
        store = Store(self.base / "db" / "state.sqlite3")
        sandbox = Sandbox(self.workspace, self.base / "backups", store)
        original = (self.workspace / "app/core/metrics.py").read_text()
        copy = sandbox.apply(analyze(scan(self.workspace), "copy", "app/core/metrics.py", "app/core/metrics-v2.py"))
        self.assertTrue((self.workspace / "app/core/metrics-v2.py").exists())
        sandbox.undo(copy)
        self.assertFalse((self.workspace / "app/core/metrics-v2.py").exists())
        move = sandbox.apply(analyze(scan(self.workspace), "move", "app/core/metrics.py", "app/core/metrics-new.py"))
        self.assertTrue((self.workspace / "app/core/metrics-new.py").exists())
        sandbox.undo(move)
        self.assertTrue((self.workspace / "app/core/metrics.py").exists())
        edit = sandbox.apply(analyze(scan(self.workspace), "modify", "app/core/metrics.py"), "print('changed')\n")
        self.assertEqual((self.workspace / "app/core/metrics.py").read_text(), "print('changed')\n")
        sandbox.undo(edit)
        self.assertEqual((self.workspace / "app/core/metrics.py").read_text(), original)

    def test_undo_protects_newer_edits(self):
        store = Store(self.base / "db" / "state.sqlite3")
        sandbox = Sandbox(self.workspace, self.base / "backups", store)
        plan = analyze(self.snapshot, "copy", "app/core/metrics.py", "app/core/copy.py")
        audit = sandbox.apply(plan)
        copied = self.workspace / "app/core/copy.py"
        copied.write_text("This is a new change", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "refusing to remove"):
            sandbox.undo(audit)
        self.assertEqual(copied.read_text(encoding="utf-8"), "This is a new change")

    def test_sandbox_disallows_symlink_escape(self):
        store = Store(self.base / "db" / "state.sqlite3")
        sandbox = Sandbox(self.workspace, self.base / "backups", store)
        outside = self.base / "outside.txt"
        outside.write_text("untouched")
        try:
            (self.workspace / "outlink").symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink not supported")
        with self.assertRaises(ValueError):
            sandbox._path("outlink", True)
        self.assertEqual(outside.read_text(), "untouched")


if __name__ == "__main__":
    unittest.main()
