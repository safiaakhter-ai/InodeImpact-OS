"""Dependency-free HTTP dashboard and local JSON API, bound to loopback only."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import threading
from typing import Any
from urllib.parse import parse_qs, urlparse
import webbrowser

from . import __version__
from .analyzer import analyze, normalize_relative
from .insights import compute_insights
from .reporting import build_report, render_html_report, report_json
from .models import Snapshot
from .sandbox import Sandbox, seed_demo
from .scanner import scan
from .storage import Store

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEMO_ROOT = PACKAGE_ROOT / "demo_workspace"
RUNTIME_ROOT = PACKAGE_ROOT / ".runtime"
STATIC_ROOT = PACKAGE_ROOT / "static"


class State:
    def __init__(self, runtime: Path = RUNTIME_ROOT, demo: Path = DEMO_ROOT):
        self.runtime = runtime.resolve()
        self.demo = demo.resolve()
        self.store = Store(self.runtime / "impact.sqlite3")
        if not self.demo.exists() or not any(self.demo.iterdir()):
            seed_demo(self.demo)
        self.sandbox = Sandbox(self.demo, self.runtime / "backups", self.store)
        self.lock = threading.RLock()
        self.current: Snapshot = scan(self.demo)
        self.store.save(self.current)

    def refresh(self, root: str | Path | None = None) -> dict[str, Any]:
        with self.lock:
            folder = Path(root).expanduser().resolve() if root else Path(self.current.root)
            previous = self.store.history(str(folder), limit=1)
            snapshot = scan(folder)
            self.store.save(snapshot)
            self.current = snapshot
            diff = self.store.compare(previous[0]["id"], snapshot.snapshot_id) if previous else None
            return {**snapshot.json(), "diff": diff, "managed": folder == self.demo}

    def dashboard(self) -> dict[str, Any]:
        with self.lock:
            return {**self.current.json(), "managed": Path(self.current.root) == self.demo, "version": __version__}

    def operate(self, request: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if Path(self.current.root) != self.demo:
                raise PermissionError("Apply is disabled for external folders. Switch to the managed demo workspace.")
            if request.get("confirm") is not True:
                raise ValueError("Explicit confirmation is required")
            self.refresh(self.demo)  # Do not trust a potentially outdated preflight.
            plan = analyze(self.current, request.get("operation", ""), request.get("source", ""), request.get("destination", ""))
            audit_id = self.sandbox.apply(plan, request.get("content"))
            result = self.refresh(self.demo)
            return {"audit_id": audit_id, "plan": plan, "snapshot": result}


class Handler(BaseHTTPRequestHandler):
    server: "DashboardServer"
    server_version = f"InodeImpact/{__version__}"

    def log_message(self, format: str, *args: object) -> None:
        print("[HTTP] " + format % args)

    def _send_json(self, payload: Any, code: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_download(self, data: bytes, media_type: str, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _check_origin(self) -> bool:
        """A malicious webpage must not be able to issue localhost state changes."""
        from urllib.parse import urlsplit
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            self._send_json({"error": "Cross-site requests are not allowed"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            expected = self.headers.get("Host", "")
            if parsed.scheme != "http" or parsed.netloc.lower() != expected.lower():
                self._send_json({"error": "Cross-origin requests are not allowed"}, 403)
                return False
        return True

    def _check_host(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].lower()
        if host and host not in ("localhost", "127.0.0.1", "[::1]"):
            self._send_json({"error": "Use localhost or 127.0.0.1"}, 403)
            return False
        return True

    def _json_body(self) -> dict[str, Any]:
        mime = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if mime != "application/json":
            raise ValueError("Content-Type must be application/json")
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > 2 * 1024 * 1024:
            raise ValueError("JSON body required (maximum 2 MiB)")
        payload = json.loads(self.rfile.read(size).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Request must be a JSON object")
        return payload

    def _dispatch(self, method: str) -> None:
        if not self._check_host() or (method == "POST" and not self._check_origin()):
            return
        url = urlparse(self.path)
        route = url.path
        args = parse_qs(url.query)
        state = self.server.state
        try:
            if method == "GET" and route == "/api/health":
                return self._send_json({"ok": True, "version": __version__, "read_only_external": True})
            if method == "GET" and route == "/api/overview":
                return self._send_json(state.dashboard())
            if method == "GET" and route == "/api/insights":
                with state.lock:
                    return self._send_json(compute_insights(state.current))
            if method == "GET" and route == "/api/report":
                fmt = args.get("format", ["html"])[0].lower()
                with state.lock:
                    report = build_report(state.current)
                if fmt == "html":
                    return self._send_download(render_html_report(report).encode("utf-8"), "text/html; charset=utf-8", "inodeimpact-report.html")
                if fmt == "json":
                    return self._send_download(report_json(report), "application/json; charset=utf-8", "inodeimpact-report.json")
                raise ValueError("Report format must be html or json")
            if method == "GET" and route == "/api/history":
                return self._send_json({"snapshots": state.store.history(state.current.root)})
            if method == "GET" and route == "/api/audit":
                return self._send_json({"events": state.store.audits()})
            if method == "GET" and route == "/api/diff":
                recent = state.store.history(state.current.root, 2)
                older = int(args["old"][0]) if "old" in args else (recent[1]["id"] if len(recent) > 1 else None)
                newer = int(args["new"][0]) if "new" in args else (recent[0]["id"] if recent else None)
                if older is None or newer is None:
                    return self._send_json({"old_id": None, "new_id": None, "added": [], "removed": [], "changed": [], "new_edges": 0, "removed_edges": 0})
                return self._send_json(state.store.compare(older, newer))
            if method == "GET" and route == "/api/view":
                source = normalize_relative(args.get("path", [""])[0])
                with state.lock:
                    node = state.current.nodes.get(source)
                    if not node or node.kind != "file" or node.size > 200_000:
                        raise ValueError("Text preview unavailable for this path")
                    location = Path(state.current.root) / source
                    if location.is_symlink() or not location.resolve().is_relative_to(Path(state.current.root)):
                        raise ValueError("Preview path is unsafe")
                    text = location.read_text(encoding="utf-8", errors="replace")[:16_000]
                return self._send_json({"path": source, "text": text})
            if method == "POST" and route == "/api/scan":
                data = self._json_body()
                root = data.get("root", "")
                if root and (not isinstance(root, str) or len(root) > 4096):
                    raise ValueError("Invalid folder path")
                return self._send_json(state.refresh(root or None))
            if method == "POST" and route == "/api/simulate":
                data = self._json_body()
                with state.lock:
                    plan = analyze(state.current, data.get("operation", ""), data.get("source", ""), data.get("destination", ""))
                    plan["can_apply"] = Path(state.current.root) == state.demo
                return self._send_json(plan)
            if method == "POST" and route == "/api/apply":
                return self._send_json(state.operate(self._json_body()))
            if method == "POST" and route == "/api/undo":
                data = self._json_body()
                with state.lock:
                    if Path(state.current.root) != state.demo:
                        raise PermissionError("Undo is restricted to the managed demo workspace")
                    if data.get("confirm") is not True:
                        raise ValueError("Explicit confirmation is required")
                    state.sandbox.undo(int(data["audit_id"]))
                    result = state.refresh(state.demo)
                return self._send_json({"snapshot": result})
            if method == "POST" and route == "/api/demo/reset":
                data = self._json_body()
                if data.get("confirm") is not True:
                    raise ValueError("Explicit confirmation is required")
                with state.lock:
                    seed_demo(state.demo, reset=True)
                    result = state.refresh(state.demo)
                    state.store.audit("reset-demo", "demo_workspace", "", "LOW", {"files": len(result["nodes"])})
                return self._send_json({"snapshot": result})
            if method == "GET" and (route == "/" or route.startswith("/static/")):
                return self._static("index.html" if route == "/" else route.removeprefix("/static/"))
            return self._send_json({"error": "Endpoint not found"}, 404)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return self._send_json({"error": str(exc)}, 400)
        except PermissionError as exc:
            return self._send_json({"error": str(exc)}, 403)
        except OSError as exc:
            return self._send_json({"error": "File-system error: " + str(exc)}, 500)

    def _static(self, name: str) -> None:
        if name not in ("index.html", "app.js", "styles.css"):
            return self._send_json({"error": "File not found"}, 404)
        asset = STATIC_ROOT / name
        content = asset.read_bytes()
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], state: State):
        self.state = state
        super().__init__(address, Handler)


def serve(port: int = 8765, open_browser: bool = True) -> None:
    state = State()
    httpd = DashboardServer(("127.0.0.1", port), state)
    url = f"http://127.0.0.1:{httpd.server_port}"
    print(f"InodeImpact OS v{__version__}")
    print(f"Dashboard: {url}")
    print("External scans are read-only. Only demo_workspace supports apply/undo.")
    print("Stop with Ctrl+C.")
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("\nServer stopped")
    finally:
        httpd.server_close()
