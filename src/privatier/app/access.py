"""Access to folders the user chose, for the macOS App Sandbox.

In the sandbox the app may only touch folders the user picked (file dialog or drag and drop). A "security-scoped
bookmark" lets the app keep that permission for a later start. Outside the sandbox, or where the Mac libraries are not
available (tests on another machine), everything here still works with plain paths and never raises.
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

try:  # pywebview brings pyobjc along on the Mac; elsewhere this is simply absent
    from Foundation import (
        NSURL,
        NSURLBookmarkCreationWithSecurityScope,
        NSURLBookmarkResolutionWithSecurityScope,
    )
except Exception:  # ImportError, or a broken install: fall back to plain paths
    NSURL = None
    NSURLBookmarkCreationWithSecurityScope = NSURLBookmarkResolutionWithSecurityScope = 0

_PLAIN = b"PATH:"  # marker for the fallback "bookmark": the plain path, used when Foundation cannot make one
_open_urls: dict[str, object] = {}  # path -> NSURL we started accessing


def sandboxed() -> bool:
    return bool(os.environ.get("APP_SANDBOX_CONTAINER_ID"))


def make_bookmark(path: str | os.PathLike) -> str | None:
    """Base64 text of an app-scoped, security-scoped bookmark for `path`; None if that is impossible."""
    p = Path(path)
    if NSURL is not None:
        try:
            url = NSURL.fileURLWithPath_(str(p))
            data, error = url.bookmarkDataWithOptions_includingResourceValuesForKeys_relativeToURL_error_(
                NSURLBookmarkCreationWithSecurityScope, None, None, None
            )
            if data is not None and error is None:
                return base64.b64encode(bytes(data)).decode("ascii")
        except Exception:
            pass
        if sandboxed():
            return None  # a plain path would give no access in the sandbox
    if not p.exists():
        return None
    return base64.b64encode(_PLAIN + str(p).encode("utf-8")).decode("ascii")


def open_bookmark(data: str) -> tuple[Path | None, bool]:
    """Resolve a bookmark and start accessing it. Returns (path or None, bookmark is stale).

    Call release(path) when done. A stale bookmark still works but should be replaced with a fresh make_bookmark().
    """
    try:
        raw = base64.b64decode(data)
    except Exception:
        return None, False
    if raw.startswith(_PLAIN):
        p = Path(raw[len(_PLAIN):].decode("utf-8", "replace"))
        return (p if p.exists() else None), False
    if NSURL is None:
        return None, False
    try:
        from Foundation import NSData

        url, stale, error = NSURL.URLByResolvingBookmarkData_options_relativeToURL_bookmarkDataIsStale_error_(
            NSData.dataWithBytes_length_(raw, len(raw)), NSURLBookmarkResolutionWithSecurityScope, None, None, None
        )
        if url is None or error is not None:
            return None, False
        url.startAccessingSecurityScopedResource()  # False is normal outside the sandbox
        path = Path(str(url.path()))
        _open_urls[str(path)] = url
        return path, bool(stale)
    except Exception:
        return None, False


def release(path: str | os.PathLike) -> None:
    """Stop accessing a folder opened with open_bookmark. Harmless for any other path."""
    url = _open_urls.pop(str(path), None)
    if url is not None:
        try:
            url.stopAccessingSecurityScopedResource()
        except Exception:
            pass


def app_support_dir() -> Path:
    """Where Privatier keeps its own settings: ~/Library/Application Support/Privatier (in the sandbox: the container)."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    folder = base / "Privatier"
    folder.mkdir(parents=True, exist_ok=True)
    return folder
