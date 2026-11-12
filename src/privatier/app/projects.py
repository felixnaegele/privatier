"""The folders the user added: the only places the app works in.

The list holds folder names, paths and the permission to open each folder again (see access.py). It holds no
data from the folders. It is kept in the app's own settings folder.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import access

_FILE = "projects.json"


class ProjectStore:
    def __init__(self, file: Path | None = None) -> None:
        self._file = Path(file) if file else access.app_support_dir() / _FILE
        self._items: list[dict] = []
        self._paths: dict[str, Path] = {}  # id -> folder that could be opened in this run
        self._load()

    def _load(self) -> None:
        try:
            saved = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = []
        changed = False
        for item in saved if isinstance(saved, list) else []:
            if not isinstance(item, dict) or not item.get("id") or not item.get("bookmark"):
                continue
            path, stale = access.open_bookmark(item["bookmark"])
            if path is not None and path.is_dir():
                self._paths[item["id"]] = path
                if stale or str(path) != item.get("path"):
                    fresh = access.make_bookmark(path)
                    item["bookmark"], item["path"], item["name"] = fresh or item["bookmark"], str(path), path.name
                    changed = True
            self._items.append(item)
        if changed:
            self._save()

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        temp = self._file.with_suffix(".tmp")
        temp.write_text(json.dumps(self._items, indent=1), encoding="utf-8")
        temp.replace(self._file)

    def listing(self) -> list[dict]:
        return [
            {"id": i["id"], "name": i.get("name", ""), "path": i.get("path", ""), "available": self.path(i["id"]) is not None}
            for i in self._items
        ]

    def path(self, project_id: str) -> Path | None:
        path = self._paths.get(project_id)
        return path if path is not None and path.is_dir() else None

    def add(self, folder: str | Path) -> str:
        """Adds a folder and returns its id. A folder that is already in the list keeps its id."""
        path = Path(folder).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("Please add a folder. To protect a single file, add the folder it is in and untick the other files.")
        bookmark = access.make_bookmark(path)
        if bookmark is None:
            raise ValueError("This folder could not be added. Please add it with the Add folder button.")
        for item in self._items:
            if item.get("path") == str(path):
                item["bookmark"] = bookmark
                self._paths[item["id"]] = path
                self._save()
                return item["id"]
        item = {"id": uuid.uuid4().hex[:12], "name": path.name, "path": str(path), "bookmark": bookmark}
        self._items.append(item)
        self._paths[item["id"]] = path
        self._save()
        return item["id"]

    def remove(self, project_id: str) -> None:
        """Takes a folder off the list. Nothing in the folder is touched."""
        path = self._paths.pop(project_id, None)
        if path is not None:
            access.release(path)
        self._items = [i for i in self._items if i["id"] != project_id]
        self._save()
