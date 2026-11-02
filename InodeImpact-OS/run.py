#!/usr/bin/env python3
"""Entry point for VS Code, the local dashboard, and command-line analysis."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from inodeimpact.analyzer import analyze
from inodeimpact.sandbox import seed_demo
from inodeimpact.reporting import build_report, render_html_report, report_json
from inodeimpact.scanner import scan
from inodeimpact.server import DEMO_ROOT, serve


def main() -> None:
    parser = argparse.ArgumentParser(description="InodeImpact OS: predictive file-operation impact analysis")
    commands = parser.add_subparsers(dest="command")
    dashboard = commands.add_parser("serve", help="start the local dashboard (default)")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument("--no-browser", action="store_true")
    scan_command = commands.add_parser("scan", help="read-only scan and print JSON")
    scan_command.add_argument("--root", default=str(DEMO_ROOT))
    impact_command = commands.add_parser("impact", help="predict the consequences of an operation")
    impact_command.add_argument("--root", default=str(DEMO_ROOT))
    impact_command.add_argument("--operation", choices=["delete", "move", "copy", "modify"], required=True)
    impact_command.add_argument("--source", required=True)
    impact_command.add_argument("--destination", default="")
    report_command = commands.add_parser("report", help="export a standalone dependency intelligence report")
    report_command.add_argument("--root", default=str(DEMO_ROOT))
    report_command.add_argument("--format", choices=["html", "json"], default="html")
    report_command.add_argument("--output", default="")
    demo_command = commands.add_parser("demo", help="create or reset the bundled demo")
    demo_command.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    if args.command in (None, "serve"):
        serve(getattr(args, "port", 8765), not getattr(args, "no_browser", False))
    elif args.command == "scan":
        print(json.dumps(scan(Path(args.root)).json(), indent=2, ensure_ascii=False))
    elif args.command == "impact":
        snapshot = scan(Path(args.root))
        print(json.dumps(analyze(snapshot, args.operation, args.source, args.destination), indent=2))
    elif args.command == "report":
        report = build_report(scan(Path(args.root)))
        result = render_html_report(report).encode("utf-8") if args.format == "html" else report_json(report)
        output = Path(args.output or ("inodeimpact-report." + args.format))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(result)
        print(f"Exported {output.resolve()} ({len(result):,} bytes)")
    elif args.command == "demo":
        count = seed_demo(DEMO_ROOT, reset=args.reset)
        print(f"Demo ready: {DEMO_ROOT} ({count} fixtures)")


if __name__ == "__main__":
    main()
