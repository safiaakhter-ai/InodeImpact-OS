"""Portable, dependency-free audit reports for the currently scanned workspace."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
from typing import Any

from .analyzer import analyze
from .insights import compute_insights
from .models import Snapshot


def build_report(snapshot: Snapshot) -> dict[str, Any]:
    insights = compute_insights(snapshot, 20)
    scenarios = []
    for item in insights["hotspots"][:8]:
        plan = analyze(snapshot, "delete", item["path"])
        scenarios.append({
            "target": item["path"], "operation": "delete",
            "risk_score": plan["risk_score"], "risk_level": plan["risk_level"],
            "direct_consumers": len(plan["direct_dependents"]),
            "transitive_consumers": len(plan["transitive_dependents"]),
            "sample_paths": plan["dependency_paths"][:3],
        })
    return {
        "report_type": "InodeImpact OS — File-System Impact Intelligence",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot": {"id": snapshot.snapshot_id, "root": snapshot.root, "scanned_at": snapshot.scanned_at},
        "summary": snapshot.json()["summary"],
        "insights": insights,
        "example_delete_preflights": scenarios,
        "scanner_warnings": snapshot.warnings,
        "interpretation": [
            "This is a static analysis of paths observed at scan time, not runtime tracing.",
            "Centrality and risk scores are heuristics, not failure probabilities.",
            "Scans may miss dynamic references, open handles, mounted volumes or external programs.",
            "No filesystem operation was performed to generate this report.",
        ],
    }


def render_html_report(report: dict[str, Any]) -> str:
    """Render a standalone report that works offline and prints cleanly."""
    h = lambda value: escape(str(value), quote=True)
    m = report["summary"]
    insights = report["insights"]
    scenarios = report["example_delete_preflights"]
    metrics = (
        ("Indexed nodes", m["nodes"]), ("File dependencies", m["dependencies"]),
        ("Potential hotspots", insights["summary"]["resources_with_consumers"]),
        ("Cyclic groups", insights["summary"]["cyclic_groups"]),
    )
    tiles = "".join(f'<div class="tile"><span>{h(name)}</span><strong>{h(value)}</strong></div>' for name, value in metrics)
    hotspot_rows = "".join(
        f'<tr><td><code>{h(x["path"])}</code></td><td>{x["direct_consumers"]}</td>'
        f'<td>{x["transitive_consumers"]}</td><td>{x["centrality_index"]}/100</td></tr>'
        for x in insights["hotspots"]
    ) or '<tr><td colspan="4">No internal dependencies detected</td></tr>'
    scenario_rows = "".join(
        f'<tr><td><code>{h(x["target"])}</code></td><td><span class="tag">{h(x["risk_level"])}</span></td>'
        f'<td>{x["risk_score"]}/100</td><td>{x["direct_consumers"] + x["transitive_consumers"]}</td></tr>'
        for x in scenarios
    ) or '<tr><td colspan="4">No scenarios available</td></tr>'
    cycle_rows = "".join(f'<li>{" → ".join(h(path) for path in group)}</li>' for group in insights["cycles"])
    warning_rows = "".join(f'<li>{h(item)}</li>' for item in report["scanner_warnings"])
    interpretation = "".join(f'<li>{h(item)}</li>' for item in report["interpretation"])
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>InodeImpact OS | Dependency Intelligence Report</title>
<style>
:root{{--ink:#182436;--muted:#586779;--line:#e0e6ed;--accent:#176d69;--bg:#f4f7f8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,-apple-system,Segoe UI,Arial,sans-serif}}
main{{max-width:1020px;margin:0 auto;padding:45px 38px 75px;background:white;min-height:100vh}}header{{border-bottom:3px solid var(--accent);padding-bottom:27px}}
.overline{{letter-spacing:2px;font-size:11px;font-weight:800;color:var(--accent)}}h1{{font-size:36px;line-height:1.18;letter-spacing:-1.4px;margin:12px 0 11px}}h2{{font-size:19px;margin:37px 0 12px;letter-spacing:-.3px}}p,.metadata{{color:var(--muted)}}.metadata{{font-size:11px;overflow-wrap:anywhere}}
.tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin:28px 0}}.tile{{border:1px solid var(--line);border-radius:10px;padding:15px;background:#f8fafb}}.tile span{{display:block;font-size:11px;color:var(--muted)}}.tile strong{{font-size:27px;display:block;color:var(--accent);margin-top:7px}}
table{{width:100%;border-collapse:collapse;text-align:left}}th{{background:#eaf3f2;color:#285651;font-size:10px;letter-spacing:.7px;text-transform:uppercase}}th,td{{padding:12px 11px;border-bottom:1px solid var(--line);vertical-align:top}}td{{font-size:12px}}code{{font:12px/1.55 ui-monospace,Consolas,monospace;overflow-wrap:anywhere}}.tag{{color:#855317;background:#fff0d8;padding:4px 9px;border-radius:20px;font-weight:700}}
.section-note{{font-size:12px;color:var(--muted)}}li{{padding:3px 0}}.disclaimer{{margin-top:33px;background:#f3f7f7;border-left:3px solid var(--accent);padding:16px 22px}}
footer{{margin-top:35px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:11px}}@media(max-width:620px){{main{{padding:26px 16px}}h1{{font-size:29px}}.tiles{{grid-template-columns:1fr 1fr}}table{{display:block;overflow-x:auto}}}}@media print{{body{{background:white}}main{{padding:0;max-width:none}}.tile,th,.disclaimer{{print-color-adjust:exact}}h2{{break-after:avoid}}tr{{break-inside:avoid}}}}
</style></head><body><main>
<header><div class="overline">INODEIMPACT OS / TECHNICAL AUDIT</div><h1>Dependency intelligence<br>report.</h1>
<p>Evidence-led file system topology and hypothetical deletion exposure.</p><div class="metadata"><b>Workspace:</b> {h(report["snapshot"]["root"])}<br>
<b>Scanned:</b> {h(report["snapshot"]["scanned_at"])} &nbsp; <b>Report generated (UTC):</b> {h(report["generated_at"])} &nbsp; <b>Snapshot:</b> {h(report["snapshot"]["id"])}</div></header>
<div class="tiles">{tiles}</div>
<h2>01 / Dependency hotspots</h2><p class="section-note">Resources ranked by the number of distinct consumers reachable through detected references. Centrality is an index, not a risk probability.</p>
<table><thead><tr><th>Resource path</th><th>Direct</th><th>Indirect</th><th>Centrality</th></tr></thead><tbody>{hotspot_rows}</tbody></table>
<h2>02 / Example preflight scenarios</h2><p class="section-note">Read-only predictions for hypothetical deletions of the highest ranked resources. Nothing was deleted.</p>
<table><thead><tr><th>Target</th><th>Risk band</th><th>Heuristic score</th><th>Consumers impacted</th></tr></thead><tbody>{scenario_rows}</tbody></table>
<h2>03 / Graph integrity observations</h2><p>Isolated regular files: <b>{insights["summary"]["isolated_files"]}</b> &nbsp; · &nbsp; Hardlink groups found: <b>{insights["summary"]["hardlink_groups"]}</b></p>
<p class="section-note">Detected circular dependency components:</p>{f'<ul>{cycle_rows}</ul>' if cycle_rows else '<p>No circular groups were detected in the indexed graph.</p>'}
<h2>04 / Scanner completeness</h2>{f'<ul>{warning_rows}</ul>' if warning_rows else '<p>No scanner warnings were reported. This does not guarantee complete dependency coverage.</p>'}
<div class="disclaimer"><strong>Methodology and limitations</strong><ul>{interpretation}</ul></div>
<footer>InodeImpact OS · Local-first OS research utility · Standalone generated document · No telemetry</footer>
</main></body></html>'''


def report_json(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
