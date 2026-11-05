"""Local audit log.

Every run appends one line per event to audit.jsonl (JSON Lines: one record
per line, readable in any text editor). The log never contains the original
sensitive values: only file names, file fingerprints (SHA-256), counts per
entity type, which detectors ran, and which tokens were introduced.

The fingerprints let anyone check later that an anonymised file is exactly
the one Privatier produced (`shasum -a 256 <file>` on Mac).
"""

from __future__ import annotations

import getpass
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

from . import __version__


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **fields) -> None:
        record = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
            **fields,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def run_started(self, action: str, **fields) -> None:
        self.write(
            "run_started",
            action=action,
            privatier_version=__version__,
            user=getpass.getuser(),
            machine=platform.node(),
            os=f"{platform.system()} {platform.release()}",
            **fields,
        )
