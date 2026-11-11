"""The Mac window. A native window showing ui.html: nothing goes through a web server or the network."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .. import __version__
from .service import AppSession, ai_model_ready

_INSTALL_HINT = """The window library is not installed yet. In Terminal, in the Privatier folder, run:

    .venv/bin/python -m pip install -e ".[app]"
"""


class Api:
    """What the page can call. Names with an underscore stay hidden from the page."""

    def __init__(self) -> None:
        self._session = AppSession()
        self._window = None

    def startup(self) -> dict:
        return {"ai_ready": ai_model_ready(), "version": __version__}

    def choose(self, kind: str):
        """Shows Mac's own dialog. Returns the chosen paths, or None when cancelled."""
        import webview

        if kind == "folder":
            chosen = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        elif kind == "key":
            chosen = self._window.create_file_dialog(
                webview.FileDialog.OPEN, allow_multiple=False, file_types=("Privatier key (*.vault)", "All files (*.*)")
            )
        else:
            chosen = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True)
        return [str(c) for c in chosen] if chosen else None

    def status(self) -> str:
        return self._session.status

    def scan(self, paths: list, use_ai: bool) -> dict:
        return self._safely(self._session.scan, paths, use_ai)

    def review(self, keep: list, extra: list) -> dict:
        return self._safely(self._session.review, keep, extra)

    def preview(self, answers: dict, ticked: list, kept_text: list) -> dict:
        return self._safely(self._session.preview, answers, ticked, kept_text)

    def export(self, level: int, password: str, answers: dict, ticked: list, kept_text: list, keep: list = None, extra: list = None) -> dict:
        return self._safely(self._session.export, level, password, answers, ticked, kept_text, keep, extra)

    def restore_info(self, paths: list) -> dict:
        return self._safely(self._session.restore_info, paths)

    def restore(self, paths: list, key_path: str, password: str) -> dict:
        return self._safely(self._session.restore, paths, key_path, password)

    def show_in_finder(self, path: str) -> None:
        subprocess.run(["open", "-R", path], check=False)

    @staticmethod
    def _safely(method, *args) -> dict:
        try:
            return method(*args)
        except Exception as exc:
            # The type only: the text of an error can quote a cell.
            return {"error": f"Something went wrong ({type(exc).__name__}). Your original files were not changed."}


def _when_ready(window) -> None:
    from webview.dom import DOMEventHandler

    def dropped(event) -> None:
        files = event.get("dataTransfer", {}).get("files", [])
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            window.evaluate_js(f"window.itemsDropped({json.dumps(paths)})")

    # Without this the page would try to open the dropped folder itself.
    window.dom.document.events.dragover += DOMEventHandler(lambda event: None, True, True)
    window.dom.document.events.drop += DOMEventHandler(dropped, True, True)


def main() -> None:
    try:
        import webview
    except ImportError:
        print(_INSTALL_HINT, file=sys.stderr)
        sys.exit(1)
    api = Api()
    html = (Path(__file__).parent / "ui.html").read_text(encoding="utf-8")
    window = webview.create_window("Privatier", html=html, js_api=api, width=1040, height=820, min_size=(760, 600))
    api._window = window
    webview.start(_when_ready, window, http_server=False)
