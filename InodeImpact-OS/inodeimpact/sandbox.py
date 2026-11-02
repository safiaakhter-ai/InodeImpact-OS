"""Controlled operation lab: NEVER mutates user-selected external scan roots.

Only an explicit, managed demo folder can be edited. Undo backups are kept
outside that folder under .runtime/backups so analyses remain reproducible.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import uuid
from typing import Any

from .analyzer import normalize_relative
from .storage import Store


DEMO_FILES: dict[str, str] = {
    "README.md": """# Atlas Operations — demo workspace\n\nThis deliberately interconnected sample is safe to experiment with.\n\n- [Configuration](config/settings.json)\n- [Architecture](docs/architecture.md)\n- [Operations report](reports/quarterly.md)\n- [Website](website/index.html)\n\nUse InodeImpact to see why deleting `config/settings.json` can affect multiple consumers.\n""",
    "app/__init__.py": "\"\"\"Internal sample application package.\"\"\"\n",
    "app/main.py": """\"\"\"Local sample service (demonstration only).\"\"\"\nfrom app.core.report import build_report\nfrom app.core.metrics import calculate_score\nfrom pathlib import Path\nimport json\n\nSETTINGS = Path('config/settings.json')\n\nif __name__ == '__main__':\n    print(build_report())\n    print('score:', calculate_score([4, 7, 10]))\n    print(json.loads(SETTINGS.read_text())['name'])\n""",
    "app/core/__init__.py": "\"\"\"Application logic package.\"\"\"\n",
    "app/core/report.py": """from app.core.metrics import calculate_score\nfrom app.core.formatter import format_score\n\ndef build_report():\n    return format_score(calculate_score([10, 20, 30]))\n""",
    "app/core/metrics.py": """def calculate_score(values):\n    return round(sum(values) / len(values), 2) if values else 0\n""",
    "app/core/formatter.py": """def format_score(score):\n    return f'Current performance: {score:.1f}'\n""",
    "config/settings.json": '{\n  "name": "Atlas Operations",\n  "theme": "northern-light",\n  "version": "1.0",\n  "report_template": "reports/template.md"\n}\n',
    "config/feature-flags.json": '{"reporting": true, "interactive_graph": true}\n',
    "docs/architecture.md": """# Atlas system overview\n\nApplication starts at [main.py](../app/main.py).\n\nThe central [configuration](../config/settings.json) is consumed by the [report](../reports/quarterly.md) and the website.\n\nThe [metrics module](../app/core/metrics.py) drives the [report builder](../app/core/report.py).\n""",
    "docs/deployment.md": """# Deployment\n\nReview [settings](../config/settings.json) and [architecture](architecture.md) before deploying.\n""",
    "reports/template.md": """# Template\n\nConfiguration reference: [settings](../config/settings.json)\n""",
    "reports/quarterly.md": """# Quarterly summary\n\nBuilt from [report module](../app/core/report.py).\nUses [settings](../config/settings.json) and [template](template.md).\n\n![Visual identity](../website/assets/logo.svg)\n""",
    "website/index.html": """<!doctype html>\n<html lang='en'>\n<head><meta charset='utf-8'><title>Atlas operations</title><link href='styles.css' rel='stylesheet'></head>\n<body><img src='assets/logo.svg' alt='Logo'><h1>Atlas operations</h1><script src='dashboard.js'></script></body>\n</html>\n""",
    "website/styles.css": """@import 'assets/palette.css';\nbody { font-family: system-ui; background: #ecf8f7; }\n""",
    "website/dashboard.js": """import { titleCase } from './utils.js';\nconsole.log(titleCase('atlas operations'));\nfetch('../config/settings.json').then(response => response.json()).then(console.log);\n""",
    "website/utils.js": """export function titleCase(value) { return value.replace(/\\b\\w/g, x => x.toUpperCase()); }\n""",
    "website/assets/logo.svg": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 120'><rect width='120' height='120' rx='24' fill='#104f64'/><path d='M24 80L60 24L96 80Z' fill='#50d4c0'/></svg>\n""",
    "website/assets/palette.css": ":root { --accent: #50d4c0; --navy: #104f64; }\n",
    "archive/old-report.md": "# Archived report\n\nThis file has no known dependencies; compare its risk with central configuration.\n",
}


def seed_demo(root: Path, reset: bool = False) -> int:
    """Create predefined harmless fixtures; only overwrite during explicit reset."""
    if reset and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for name, content in DEMO_FILES.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if reset or not target.exists():
            target.write_text(content, encoding="utf-8")
    return len(DEMO_FILES)


def _fingerprint(path: Path) -> str:
    """Detect intervening edits so undo never silently overwrites a changed copy."""
    digest = hashlib.sha256()
    paths = [path]
    if path.is_dir() and not path.is_symlink():
        paths += sorted(path.rglob("*"), key=str)
    for item in paths:
        digest.update(str(item.relative_to(path.parent)).encode("utf-8"))
        if item.is_symlink():
            digest.update(b"SYMLINK")
            digest.update(str(item.readlink()).encode("utf-8"))
        elif item.is_file():
            with item.open("rb") as file:
                for chunk in iter(lambda: file.read(65536), b""):
                    digest.update(chunk)
        elif item.is_dir():
            digest.update(b"DIRECTORY")
    return digest.hexdigest()


class Sandbox:
    def __init__(self, workspace: Path, backup_dir: Path, store: Store):
        self.root = workspace.resolve()
        self.backups = backup_dir.resolve()
        self.store = store
        self.backups.mkdir(parents=True, exist_ok=True)

    def _path(self, relative: str, must_exist: bool = False) -> Path:
        name = normalize_relative(relative)
        target = self.root.joinpath(*name.split("/"))
        # Forbid symlink ancestors and the symlink itself to avoid workspace escape.
        cursor = self.root
        for part in name.split("/"):
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("Sandbox actions on symbolic links or symlink parents are disabled")
        try:
            target.parent.resolve(strict=False).relative_to(self.root)
        except ValueError:
            raise ValueError("Path leaves the managed demo workspace") from None
        if must_exist and not target.exists():
            raise ValueError(f"Path no longer exists: {name}")
        return target

    def apply(self, plan: dict[str, Any], content: str | None = None) -> int:
        operation = plan["operation"]
        source = self._path(plan["source"], must_exist=True)
        destination = self._path(plan["destination"]) if plan.get("destination") else None
        if destination and destination.exists():
            raise ValueError("Destination already exists")
        if operation == "modify":
            if not source.is_file() or not isinstance(content, str):
                raise ValueError("Modifying requires a text file and replacement text")
            if len(content.encode("utf-8")) > 1024 * 1024:
                raise ValueError("Replacement text is limited to 1 MiB")
        if operation not in {"delete", "move", "copy", "modify"}:
            raise ValueError("Unsupported operation")
        backup = ""
        fingerprint = ""
        operation_key = uuid.uuid4().hex
        if operation in {"delete", "modify"}:
            backup_path = self.backups / operation_key
            if operation == "delete":
                shutil.move(str(source), str(backup_path))
            else:
                shutil.copy2(source, backup_path)
                source.write_text(content, encoding="utf-8")
                fingerprint = _fingerprint(source)
            backup = str(backup_path)
        elif operation in {"copy", "move"}:
            assert destination is not None
            destination.parent.mkdir(parents=True, exist_ok=True)
            if operation == "move":
                shutil.move(str(source), str(destination))
            elif source.is_dir():
                shutil.copytree(source, destination, symlinks=True)
            else:
                shutil.copy2(source, destination, follow_symlinks=False)
            if operation == "copy":
                fingerprint = _fingerprint(destination)
        details = {"backup": backup, "risk_score": plan["risk_score"], "fingerprint": fingerprint}
        return self.store.audit("apply:" + operation, plan["source"], plan.get("destination", ""), plan["risk_level"], details)

    def undo(self, audit_id: int) -> None:
        audit = self.store.get_audit(audit_id)
        if not audit or not audit["action"].startswith("apply:"):
            raise ValueError("Original operation not found")
        if self.store.was_undone(audit_id):
            raise ValueError("Operation has already been undone")
        operation = audit["action"].split(":", 1)[1]
        source = self._path(audit["source"])
        destination = self._path(audit["destination"]) if audit["destination"] else None
        backup = Path(audit["details"].get("backup", "")) if audit["details"].get("backup") else None
        if operation == "delete":
            if source.exists() or not backup or not backup.exists():
                raise ValueError("Cannot undo: source path occupied or recovery backup missing")
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(backup), str(source))
        elif operation == "modify":
            if not backup or not backup.exists() or not source.is_file():
                raise ValueError("Cannot undo: modified file or recovery backup missing")
            if audit["details"].get("fingerprint") != _fingerprint(source):
                raise ValueError("File changed after the operation; refusing to overwrite newer edits")
            shutil.copy2(backup, source)
            backup.unlink()
        elif operation == "move":
            if not destination or not destination.exists() or source.exists():
                raise ValueError("Cannot undo: destination missing or source path occupied")
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(source))
        elif operation == "copy":
            if not destination or not destination.exists():
                raise ValueError("Cannot undo: copied destination missing")
            if audit["details"].get("fingerprint") != _fingerprint(destination):
                raise ValueError("Copied destination changed since the operation; refusing to remove newer edits")
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        else:
            raise ValueError("Unsupported undo operation")
        self.store.audit("undo", audit["source"], audit["destination"], "LOW", {"undo_of": audit_id})
