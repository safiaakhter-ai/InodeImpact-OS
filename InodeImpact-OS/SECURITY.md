# Security and operational boundaries

InodeImpact OS is a local teaching/research utility, not production-grade file-management software.

**Default:** The Python server only listens at `127.0.0.1`. The dashboard is fully local. It doesn't upload scanned paths or content to a third-party service. Avoid forwarding the port to untrusted networks.

**Scanned external folders:** are readable but cannot be mutated via `/api/apply` or `/api/undo`. A selected directory may contain sensitive file names or content; choose roots responsibly. The file-preview endpoint returns up to 16,000 characters only from a small regular file that the scanner indexed.

**Sandbox:** Only the package's `demo_workspace` root can be modified through the API. Apply/undo requires `confirm: true`; the browser also prompts before applying. Traversal, absolute paths, symlink paths and pre-existing destination paths are rejected. A scan is refreshed before applying.

**Limitations:** If another application changes the demo after an operation, undo could fail or lose newer changes (particularly when undoing copies). Reset discards demo edits. SQLite writes are not a crash-safe filesystem journal. Static reference extraction does not verify all dynamic dependencies. Do not treat a LOW risk score as proof of safety.

**Supported environment:** Python 3.10+ (3.11+ recommended), local trusted developer workstation. Do not deploy publicly or run with administrator privileges.

**Request integrity in v1.1:** POST endpoints require `Content-Type: application/json` and reject cross-site Fetch Metadata and Origin values that do not match the server's Host. These are browser-request mitigations, not an authentication system. A process already running on the user's machine may still make local requests. Never expose this local development server to other machines.

**Report privacy:** HTML and JSON exports contain scanned pathnames and technical relationships. Inspect their contents before sharing. The tool does not automatically upload reports.
