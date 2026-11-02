"""Integration smoke tests against an ephemeral loopback port."""
from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest

from inodeimpact.server import DashboardServer, State


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.demo = root / "demo"
        cls.external = root / "external"
        cls.external.mkdir()
        (cls.external / "document.md").write_text("not editable via this server")
        cls.state = State(root / ".runtime", cls.demo)
        cls.server = DashboardServer(("127.0.0.1", 0), cls.state)
        cls.port = cls.server.server_port
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.state.store.connection.close()
        cls.tmp.cleanup()

    def call(self, method, endpoint, payload=None, extra_headers=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=4)
        headers = {"Content-Type": "application/json"}
        if extra_headers: headers.update(extra_headers)
        conn.request(method, endpoint, body=json.dumps(payload) if payload is not None else None, headers=headers)
        res = conn.getresponse()
        data = res.read()
        conn.close()
        return res.status, json.loads(data)

    def test_health(self):
        status, result = self.call("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])

    def test_insights_and_reports(self):
        code, result = self.call("GET", "/api/insights")
        self.assertEqual(code, 200)
        self.assertIn("hotspots", result)
        conn = HTTPConnection("127.0.0.1", self.port, timeout=4)
        conn.request("GET", "/api/report?format=html")
        response = conn.getresponse()
        body = response.read().decode('utf-8')
        self.assertEqual(response.status, 200)
        self.assertIn('attachment; filename="inodeimpact-report.html"', response.getheader('Content-Disposition'))
        self.assertIn('<!doctype html>', body)
        conn.close()
        code, result = self.call("GET", "/api/report?format=not-supported")
        self.assertEqual(code, 400)

    def test_cross_site_mutation_is_denied(self):
        code, result = self.call("POST", "/api/demo/reset", {"confirm": True}, {"Origin": "https://outside.example"})
        self.assertEqual(code, 403)
        self.assertIn('Cross-origin', result['error'])
        code, result = self.call("POST", "/api/demo/reset", {"confirm": True}, {"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(code, 403)

    def test_simple_cross_site_content_type_is_denied(self):
        code, result = self.call("POST", "/api/demo/reset", {"confirm": True}, {"Content-Type": "text/plain"})
        self.assertEqual(code, 400)
        self.assertIn('Content-Type', result['error'])

    def test_preflight(self):
        status, result = self.call("POST", "/api/simulate", {"operation": "delete", "source": "config/settings.json"})
        self.assertEqual(status, 200)
        self.assertGreaterEqual(result["risk_score"], 50)

    def test_external_apply_is_denied(self):
        self.call("POST", "/api/scan", {"root": str(self.external)})
        status, result = self.call("POST", "/api/apply", {"operation": "delete", "source": "document.md", "confirm": True})
        self.assertEqual(status, 403)
        self.assertTrue((self.external / "document.md").is_file())
        self.call("POST", "/api/demo/reset", {"confirm": True})

    def test_apply_requires_explicit_confirmation(self):
        status, _ = self.call("POST", "/api/apply", {"operation": "delete", "source": "archive/old-report.md"})
        self.assertEqual(status, 400)

    def test_apply_and_undo(self):
        self.call("POST", "/api/demo/reset", {"confirm": True})
        status, result = self.call("POST", "/api/apply", {"operation": "delete", "source": "archive/old-report.md", "confirm": True})
        self.assertEqual(status, 200)
        self.assertFalse((self.demo / "archive/old-report.md").exists())
        status, _ = self.call("POST", "/api/undo", {"audit_id": result["audit_id"], "confirm": True})
        self.assertEqual(status, 200)
        self.assertTrue((self.demo / "archive/old-report.md").exists())

    def test_snapshot_history(self):
        self.call("POST", "/api/demo/reset", {"confirm": True})
        status, result = self.call("GET", "/api/history")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(result["snapshots"]), 2)
        status, diff = self.call("GET", "/api/diff")
        self.assertEqual(status, 200)
        self.assertIn("changed", diff)


if __name__ == "__main__":
    unittest.main()
