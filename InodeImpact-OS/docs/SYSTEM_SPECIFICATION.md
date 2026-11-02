# InodeImpact OS — System specification

## Scope

**Category:** operating-systems learning/research utility, not an operating system kernel.

**Problem:** changing one pathname can disrupt several downstream consumers. Ordinary directory browsing exposes metadata but often does not surface static reference relationships before an operation.

**Objective:** provide inspectable evidence about possible dependency impact in an offline application, then demonstrate restricted file operations and recovery in a disposable workspace.

## Functional requirements

| ID | Requirement | Implementation |
|---|---|---|
| F-01 | Scan a chosen directory without mutating it | `scanner.scan` |
| F-02 | Show device, inode, link count, permissions, size and file hash | `models.Node`, File Explorer |
| F-03 | Extract internal static references | AST imports and bounded reference matching |
| F-04 | Visualize the consumer → resource graph | SVG dashboard |
| F-05 | Simulate delete, move, copy and modify | `analyzer.analyze` |
| F-06 | Explain direct and indirect blast radius | Reverse BFS, `dependency_paths` |
| F-07 | Show a deterministic score-factor breakdown | `risk_factors` |
| F-08 | Rank hotspots and reveal cycles and inode-sharing | `insights.compute_insights` |
| F-09 | Retain/compare scan snapshots | SQLite `storage.Store` |
| F-10 | Generate downloadable reports | `reporting.build_report` |
| F-11 | Apply/undo operations only in a disposable test root | `sandbox.Sandbox`, guarded API |
| F-12 | Start and test locally from VS Code | `run.py`, `.vscode`, launchers |

## Non-functional design

- **Offline:** the application does not need cloud services, tokens or network dependencies. Browser assets are included.
- **Portability:** Python 3.10 or later, standard library only for application runtime.
- **Bounded reads:** scanner defaults to a maximum of 4,000 indexed nodes and reads supported text files up to 768 KiB; non-directory symlinks are indexed but not traversed.
- **Privacy:** paths and metadata are processed on the local machine and snapshot history resides in `.runtime`, which is excluded from the published source archive.
- **Safety:** server binds to loopback; POST operations require JSON with origin checks; external roots cannot be mutated; demo mutations require confirmation.
- **Inspectability:** algorithmic risk is presented as a heuristic; reports include warnings and limitations.

## Architecture

```text
Dashboard (HTML/CSS/vanilla JS)
    |
Local loopback JSON API (server.py)
    |
    +-- Scanner (read-only metadata + static references)
    |      -> Snapshot (nodes and directed edges)
    |
    +-- Analyzer (reverse BFS + dependency evidence)
    |
    +-- Insights (reachability + Tarjan SCC + hardlink grouping)
    |
    +-- Reporting (HTML / JSON standalone output)
    |
    +-- Storage (SQLite snapshot history / audit log)
    |
    +-- Sandbox (confirmed operations on demo only)
```

Edges are directed from *consumer* to *resource*. A reverse breadth-first search yields all indexed consumers possibly affected by losing or changing the selected resource. The analyzer reconstructs shortest evidence chains using a successor pointer for each reached consumer. Source evidence is preserved in scanner edges. Tarjan strongly connected components expose graph cycles; grouping by `(device, inode)` helps identify hardlinked regular files.

## Risk model

For each operation, the score is the sum of fixed, explainable components, capped at 100:

- Operation baseline: delete 18, move 13, modify 13, copy 2.
- Direct consumers: up to 43 points.
- Indirect consumers: up to 22 points.
- Duplicate inbound references: up to 10 points.
- Large subtree scope for delete or move: up to 12 points.
- Outgoing references in moved files: up to 12 points.

The bands are LOW below 25, MODERATE at 25–49, HIGH at 50–74, and CRITICAL at 75–100. This is a **prioritization score** and should never be interpreted as an empirically validated probability. Copy operations preserve the original resource, so their dependency disruption is assessed separately from deletion/renaming.

## Limits and future research

The analysis does not trace active file descriptors or live kernel events; it does not resolve all language package systems, embedded binary references, dynamically generated filenames or consumers outside the scan boundary. Current restoration is a teaching mechanism rather than a crash-safe transaction journal. The next engineering steps would be runtime filesystem event correlation, language-specific parsers, calibrated impact models and fault-injection experiments.

## Test strategy

Use the bundled 31 `unittest` cases. The suite covers scanning, import/reference extraction, snapshot change detection, dependency traversal, explainable chains, graph cycles, hardlinks, static report generation, sandbox operations/undo, external mutation denial, local API preflight, downloads and cross-site rejection. CI is configured to test Windows and Ubuntu on three Python versions.
