# InodeImpact OS — Demonstration walkthrough

This demonstration uses the included disposable `demo_workspace`. It shows system behavior rather than making claims about all possible real-world dependencies.

## Before the demonstration

- Extract the project ZIP and open the `InodeImpact-OS` directory in Visual Studio Code.
- On Windows, double-click `start_windows.bat`. On other platforms, use the matching launcher or run `python run.py` from the project directory.
- If your default browser does not open, navigate to `http://127.0.0.1:8765`.
- Verify that the top-right status reads **MANAGED SANDBOX**.

## Walkthrough (approximately 5 minutes)

**1. System overview (45 seconds).** Identify scanned nodes, dependency edges, total size and unreferenced files. Explain that the graph is built from filesystem metadata and references in readable source/document files. A node is not a live process; an edge is not a kernel-enforced dependency.

**2. File inspector (45 seconds).** In File Explorer, select `config/settings.json`. Show its inode, device, link count, permissions, SHA-256, inbound references and outbound references. Inode identity varies by operating system and filesystem.

**3. Dependency Insights (60 seconds).** Select the new Dependency Insights section. Show the top hotspot table and direct versus transitive consumers. Explain why `config/settings.json` is influential, and highlight any cyclic groups. Export an HTML report and point out that it is usable without an internet connection.

**4. Predictive preflight (70 seconds).** Open Impact Studio, choose **Delete**, set source to `config/settings.json`, then click **Analyze impact**. Expand **How this risk score was calculated** and **Trace why files are affected**. A trace can show `website/index.html → website/dashboard.js → config/settings.json`. The score is a heuristic, not a measured failure probability. Run a second preflight for `archive/old-report.md` and compare its predicted impact.

**5. Contained execution and recovery (45 seconds).** Return to the managed demo, select the isolated archived report, simulate its deletion, then explicitly apply it in the sandbox. Go to Audit & Recovery, click **Undo**, and show that the file is restored. Explain that ordinary external folder scans are read-only and that demo undo is not a transactional filesystem guarantee.

**6. History and verification (35 seconds).** Open Snapshot History, compare two recent scans, and discuss path, content and edge differences. Use **Demo reset** to return to clean sample data; this intentionally discards any changes inside `demo_workspace`.

## Questions a reviewer may ask

**Is this a new kernel or bootable operating system?** No. It is an OS-domain utility built on standard filesystem APIs. It demonstrates inode metadata, pathname resolution, dependency graphs, safe operation simulation and audit/recovery.

**How does prediction work?** The scanner creates directed references from consumers to resources. The analyzer traverses reverse edges from a proposed target and reports direct and transitive consumers. Risk weights account for consumer breadth, repeated references, subtree scope and operation-specific factors.

**Why can a LOW risk result still be unsafe?** Runtime-generated paths, loaded modules, databases, open file handles and references outside the indexed root may be invisible to the scanner.

**Why can an inode appear different on Windows?** Python maps metadata through the host filesystem and operating system. Device/inode semantics are not always the same as Linux ext4.

**How are user files protected?** The web API can scan externally selected roots but cannot apply delete/move/copy/modify to them. Only an included demo directory is eligible for confirmed operations, with recorded recovery steps.

## Validation checklist

- Dashboard starts without third-party Python installations.
- Clicking a resource opens its inspector.
- The preflight shows dependency chain evidence and score factors.
- HTML and JSON reports download from Dependency Insights.
- External roots cannot be mutated through the API.
- `python -m unittest discover -s tests -v` runs 31 tests on a supported local Python installation.
