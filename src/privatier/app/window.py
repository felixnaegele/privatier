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
        return {"ai_ready": ai_model_ready(), "version": __version__, "projects": self._safely(self._session.projects)}

    def _dialog(self, kind: str):
        """Shows Mac's own dialog. Choosing something there is what gives the app access to it."""
        import webview

        if kind == "folder":
            try:
                chosen = _choose_folder()
            except Exception:  # the plain dialog of the window library, without the explaining line
                chosen = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        else:
            chosen = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True)
        return [str(c) for c in chosen] if chosen else None

    def choose(self, kind: str):
        return self._dialog("folder" if kind == "folder" else "files")

    def add_project(self):
        chosen = self._dialog("folder")
        return self._safely(self._session.add_project, chosen) if chosen else None

    def add_project_paths(self, paths: list) -> dict:
        return self._safely(self._session.add_project, paths)

    def remove_project(self, project_id: str) -> dict:
        return self._safely(self._session.remove_project, project_id)

    def open_project(self, project_id: str, use_ai: bool) -> dict:
        return self._safely(self._session.open_project, project_id, use_ai)

    def set_files(self, selected: list) -> dict:
        return self._safely(self._session.set_files, selected)

    def status(self) -> str:
        return self._session.status

    def set_column(self, ref: list, value=None) -> dict:
        return self._safely(self._session.set_column, ref, value)

    def review(self, keep: list, extra: list) -> dict:
        return self._safely(self._session.review, keep, extra)

    def preview(self, answers: dict, ticked: list, kept_text: list) -> dict:
        return self._safely(self._session.preview, answers, ticked, kept_text)

    def export(self, level: int, password: str, answers: dict, ticked: list, kept_text: list, keep: list = None, extra: list = None) -> dict:
        return self._safely(self._session.export, level, password, answers, ticked, kept_text, keep, extra)

    def restore_info(self, paths: list) -> dict:
        return self._safely(self._session.restore_info, paths)

    def restore(self, paths: list, password: str) -> dict:
        return self._safely(self._session.restore, paths, password)

    def show_in_finder(self, path: str) -> None:
        try:  # works inside the macOS sandbox, where starting another program does not
            from AppKit import NSURL, NSWorkspace

            NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_([NSURL.fileURLWithPath_(str(path))])
        except Exception:
            subprocess.run(["open", "-R", path], check=False)

    @staticmethod
    def _safely(method, *args):
        try:
            return method(*args)
        except PermissionError:
            return {"error": "macOS did not let Privatier open this. Add the folder again with Add folder, then try once more."}
        except Exception as exc:
            # The type only: the text of an error can quote a cell.
            return {"error": f"Something went wrong ({type(exc).__name__}). Your original files were not changed."}


def _choose_folder() -> list[str] | None:
    """Mac's folder dialog, saying what choosing a folder means. Runs on the main thread, as dialogs must."""
    import threading

    import AppKit
    from PyObjCTools import AppHelper

    done = threading.Semaphore(0)
    result: dict = {}

    def show() -> None:
        try:
            panel = AppKit.NSOpenPanel.openPanel()
            panel.setCanChooseFiles_(False)
            panel.setCanChooseDirectories_(True)
            panel.setCanCreateDirectories_(True)
            panel.setAllowsMultipleSelection_(False)
            panel.setMessage_("Choose the folder of one project. Privatier can only work inside the folders you add.")
            panel.setPrompt_("Add Folder")
            if panel.runModal() == AppKit.NSModalResponseOK:
                result["paths"] = [str(url.path()) for url in panel.URLs()]
        except Exception as exc:
            result["error"] = exc
        finally:
            done.release()

    AppHelper.callAfter(show)
    done.acquire()
    if "error" in result:
        raise result["error"]
    return result.get("paths")


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
    window = webview.create_window("Privatier", html=html, js_api=api, width=1040, height=820, min_size=(860, 600))
    api._window = window
    webview.start(_when_ready, window, http_server=False)


def window_test() -> int:
    """Opens the real window for a few seconds and checks that the page is shown. Prints verdicts only."""
    import threading
    import time

    import webview

    api = Api()
    html = (Path(__file__).parent / "ui.html").read_text(encoding="utf-8")
    window = webview.create_window("Privatier", html=html, js_api=api, width=1040, height=820, min_size=(860, 600))
    api._window = window
    seen: dict = {}

    def look() -> None:
        try:
            seen["loaded"] = bool(window.events.loaded.wait(20))
            if not seen["loaded"]:
                return
            time.sleep(3)  # the page asks the app for its start data and then draws itself
            seen["text"] = window.evaluate_js("document.body ? document.body.innerText.length : -1")
            seen["api"] = window.evaluate_js("typeof (window.pywebview && window.pywebview.api && window.pywebview.api.startup)")
        except Exception as exc:
            seen["error"] = type(exc).__name__

    def check(window) -> None:
        thread = threading.Thread(target=look, daemon=True)
        thread.start()
        thread.join(40)
        window.destroy()

    webview.start(check, window, http_server=False)
    checks = [
        ("the page finished loading", seen.get("loaded") is True),
        ("the page shows text", isinstance(seen.get("text"), (int, float)) and seen["text"] > 50),
        ("the page can talk to the app", seen.get("api") == "function"),
    ]
    for label, good in checks:
        print(f"[{'ok' if good else 'FAIL'}] window: {label}")
    if "error" in seen:
        print(f"[info] window: {seen['error']}")
    passed = all(good for _, good in checks)
    print("WINDOW TEST PASSED" if passed else "WINDOW TEST FAILED")
    return 0 if passed else 1
