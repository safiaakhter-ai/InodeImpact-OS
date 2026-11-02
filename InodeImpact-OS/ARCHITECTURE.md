# InodeImpact OS — technical architecture and project report

## 1. Problem statement

File-system operations are often requested against a pathname without considering the many scripts, modules, documents, pages and links that refer to the file. The observable outcome of a delete, move or modification can affect multiple downstream consumers. A pathname-only UI cannot expose that influence.

**Research question:** Can lightweight static dependency extraction combined with inode metadata and reverse-graph analysis produce an explainable preflight estimate for common file operations?

## 2. Objectives

1. Enumerate file-system metadata and expose inode-like identity and hard-link counts.
2. Recover a bounded approximation of the dependency graph from common source and document formats.
3. Calculate direct and transitive consumer sets of a proposed operation.
4. Display explainable risk signals and supporting path evidence.
5. Persist scans and detect filesystem/graph changes.
6. Provide a safely contained operation laboratory with recovery/audit support.

## 3. Components and contracts

- `scanner.scan(root)` returns a `Snapshot(root, nodes, edges, scanned_at, warnings)`. `Node` contains path, kind, inode, device, link count, size, permissions, timestamp, content hash, extension and optional symlink target.
- `Edge(source,target,reason,evidence)` establishes a static consumer-to-resource relation. Example: `website/index.html -> website/styles.css` with `web-reference` evidence `styles.css`.
- `analyzer.analyze(snapshot,operation,source,destination)` returns the operation summary, risk estimate, incoming/outgoing reference evidence, impacted paths, hop distance, notes and mitigations. No mutation happens here.
- `storage.Store` persists snapshots as JSON in local SQLite and records operation audit entries.
- `sandbox.Sandbox` implements restricted operations and undo for a single managed workspace.
- `server.Handler` exposes simple JSON endpoints and serves local assets, while `State` coordinates scan state and serialized mutation.

## 4. Metadata and identity

The scanner uses `DirEntry.stat(follow_symlinks=False)` and the standard `stat` module. For regular files, it reads at most 768 KiB to compute SHA-256 and extract recognized references. A hard link shares a device/inode identity with another pathname on suitable file systems, but removing a pathname does not imply removing inode data if another link remains.

Symlinks are indexed as symlinks; the scanner does not follow directory symlinks, avoiding traversal loops and external directory reads. Internal symlink target paths can become explicit graph edges. On some filesystems or operating systems, inode fields can be unavailable or represent different identities; interpretation is platform-dependent.

## 5. Dependency resolution

The scanner takes two passes:

- Pass A: enumerate nodes and build a set of paths within the scan root.
- Pass B: inspect recognized small text files. Python import statements are extracted with `ast`; document links and selected HTML/CSS/JS/quoted paths are found with bounded regex patterns; symlink references derive from link-target strings.

Only references resolving to indexed paths produce graph edges. Edges are deduplicated per `(source,target,reason)` and preserve a short evidence string. Directory paths are indexed but do not implicitly create dependency edges; containment is a separate, structural relationship.

**Known limitations:** regex patterns can over- or under-match, Python package import rules can be more complex than this resolver, external references are intentionally omitted, runtime or dynamic imports are invisible, and file paths referenced without recognizable syntax can be missed.

## 6. Impact traversal

Let `G = (V,E)` be a directed graph where an edge `A -> B` denotes that A statically depends on B. Construct a reverse adjacency map `pred[B] = {A | A -> B}`. For a target file or subtree `S`:

```text
scope = all indexed nodes equal to or descended from selected source
queue = every external predecessor of any node in scope, distance = 1
while queue not empty:
    take consumer and distance
    if not already recorded with shorter distance:
        record distance
        enqueue predecessors of that consumer at distance + 1
impact_set = visited external consumers
```

Direct consumers have hop distance 1; other reachable consumers are transitive. When deleting/moving a path, these existing references may no longer resolve. When modifying content, they may be behaviorally affected; when copying a path, the original consumers remain pointed to the original resource.

**Time complexity:** metadata enumeration is approximately O(N) path operations plus file bytes read; hashing and parsing are O(B) for bounded scanned bytes; reverse adjacency creation is O(E); BFS is O(V+E) in the reachable subgraph. This implementation also sorts edges and selected outputs, so total cost includes O(E log E), and uses bounded path counts for predictable interactive use.

## 7. Scoring

The current 0–100 score is deterministic, not an empirical probability:

- Starting score: delete 18; move 13; modify 13; copy 2.
- Direct consumers: at most 43 additional points, 17 each.
- Transitive consumers: at most 22 additional points, 7 each.
- Repeated inbound edges: limited additional points.
- Folder scope and outgoing references on move: limited additional points.
- Result capped at 100. Bands: Low 0–24, Moderate 25–49, High 50–74, Critical 75–100.

Incoming evidence and hard-link notes are shown beside the score. A risk category is a **relative prioritization signal**, not a guarantee of actual failure frequency or breakage severity.

## 8. Snapshot comparisons

An initial scan is captured when the local server starts; each subsequent scan adds another SQLite snapshot. Node addition/removal is detected by path set differences, and changes are detected from SHA-256 (for small regular files), size, file kind, link target or permissions. Dependency-edge sets are also compared.

Limitations: modifications to large files that preserve size/metadata might be missed, file renames show as an addition and a deletion, and the database grows with each scan. Production-grade differential scanning would use persistent indices and incremental OS change notifications.

## 9. Isolation and recovery

External roots have read-only scans and simulations. The API rejects apply and undo requests when the active root is not exactly the managed `demo_workspace`. Path validation rejects absolute/traversal and symlinked paths. Every apply operation is explicitly confirmed and recorded.

For deletion, the object is moved to `.runtime/backups/<unique id>`. For text modification, the previous file is copied there. Moves and copies have inverse operations. Undo checks whether the necessary source/destination remains available, but is not a crash-consistent transaction manager. Undo of a copied file can remove data edited later; therefore, use the demo sandbox only.

## 10. Verification and evaluation

Unit and integration tests cover the demo graph, Python and web reference extraction, downstream impact, low-impact isolated targets, copies, malicious paths, symlink traversal safety, snapshot changes, guarded operations, undo and HTTP endpoints. Run:

```bash
python -m unittest discover -s tests -v
```

A deeper research evaluation could benchmark recall against a manually labelled reference graph across diverse repositories, measure wall-clock scan time versus node count, and measure risk ranking against controlled failure-injection outcomes. These performance numbers have **not** been collected here and should not be fabricated for a submission.

## 11. Originality statement

The unique contribution of this *implementation* is the combined workflow for inode-aware metadata inspection, static multi-format references, graph-based operation preflight, temporal comparison, and guarded hands-on recovery. It is not verified to be the first such system worldwide. Similar ideas exist across filesystem tooling, build systems, refactoring tools and dependency analyzers; a GitHub or literature novelty search would be needed before making exclusivity claims.

## 11. Version 1.1: dependency topology and evidence tracing

The new `insights.py` module builds two adjacency indexes (consumer → dependency and resource → consumers) from the single recorded graph. For each resource with inbound references, a reverse graph traversal counts unique directly and transitively reachable consumers. A priority index weights those counts. The same module uses an iterative Tarjan SCC algorithm to find nontrivial cyclic components and groups regular files sharing `(st_dev, st_ino)`.

The analyzer additionally retains shortest-path successor links during reverse BFS. `dependency_paths` includes a sequence from each affected consumer toward a source path, with each step sourced from an actual recorded static edge. The risk estimate exposes each component in `risk_factors`, making the heuristic auditable.

The report builder consumes a single snapshot, creates a compact technical summary with ranked hotspots and representative hypothetical deletion preflights, and renders standalone HTML or structured JSON. Reports are read-only and contain scanner-root paths, which may be sensitive if shared outside the local machine.

### Complexity notes

Graph setup and Tarjan SCC are O(V + E). Per-resource reachability is O(H × (V + E)) in the worst case, where H is the number of resources with inbound references. This is suitable for the bounded default 4,000-node scan, not a claim of linear total complexity for large enterprise codebases. Report size is bounded by selected hotspot and trace limits.

### API request boundaries

State-changing POST requests require `application/json` and reject mismatched Origin and `Sec-Fetch-Site: cross-site` metadata. The server binds to IPv4 loopback. Mutations are still limited to the included demo root and require `confirm: true`. Origin checks reduce browser-originated request forgery but should not be treated as local authentication against another process with user privileges.
