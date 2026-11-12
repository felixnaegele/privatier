"""Where the app keeps its own files: in one folder inside the project.

    Studie/                          the project
      Privatier/                     made by the app, holds the empty marker file .privatier
        Key - keep private/          key.vault, audit.jsonl, privacy_report.txt
        Studie_pseudonymised/        a copy
        Restored/<name>_restored/    restored results

A folder that directly holds the marker file is never read: not as data, not as evidence, and it is not
listed as skipped. So a copy is never anonymised again, and the key never goes into a copy.

Only this module creates the marker, and only in <project>/Privatier. A folder that is already there without
the marker and holds anything is left alone, as it may be the user's own data.

The command line does not use this layout: it keeps writing next to the project folder.
"""

from __future__ import annotations

from pathlib import Path

MARKER_FILE = ".privatier"
PRIVATIER_DIR_NAME = "Privatier"
KEY_DIR_NAME = "Key - keep private"
RESTORED_DIR_NAME = "Restored"
_OF_NO_ACCOUNT = {".DS_Store"}  # the Finder leaves it in any folder it has shown


class PrivatierFolderError(ValueError):
    """The folder for Privatier's own files cannot be made, or is not Privatier's."""


def privatier_dir(project: Path) -> Path:
    return Path(project) / PRIVATIER_DIR_NAME


def key_dir(project: Path) -> Path:
    """Where the key, the audit log and the privacy report of a project are."""
    return privatier_dir(project) / KEY_DIR_NAME


def restored_dir(project: Path) -> Path:
    """Restored results go into a folder of their own inside this one."""
    return privatier_dir(project) / RESTORED_DIR_NAME


def is_marked(folder: Path) -> bool:
    """Privatier's own folder: it directly holds the marker, as a real file."""
    marker = Path(folder) / MARKER_FILE
    return marker.is_file() and not marker.is_symlink()


def marked_folder_above(path: Path, project: Path) -> Path | None:
    """The marked folder inside the project that `path` lies in (or is), if any. The project itself never counts."""
    path, project = Path(path).resolve(), Path(project).resolve()
    if path == project or not path.is_relative_to(project):
        return None
    for folder in (path, *path.parents):
        if folder == project:
            return None
        if is_marked(folder):
            return folder
    return None


def ensure_privatier_dir(project: Path) -> Path:
    """Make <project>/Privatier with its marker, or return it if it is there already. Never marks anything else."""
    project = Path(project)
    if not project.is_dir():
        raise FileNotFoundError(f"Folder not found: {project}")
    folder = privatier_dir(project)
    if folder.is_symlink():
        raise PrivatierFolderError(
            f"{folder} is a link to another place. Privatier keeps its files inside the project only, so it was not used."
        )
    if folder.exists() and not folder.is_dir():
        raise PrivatierFolderError(f"{folder} is a file, so Privatier cannot make its folder there. Please rename it.")
    if folder.is_dir():
        if is_marked(folder):
            return folder
        if (folder / MARKER_FILE).exists() or (folder / MARKER_FILE).is_symlink():
            raise PrivatierFolderError(f"{folder / MARKER_FILE} is not an ordinary file, so the folder was not used.")
        if any(item.name not in _OF_NO_ACCOUNT for item in folder.iterdir()):
            raise PrivatierFolderError(
                f"A folder called {PRIVATIER_DIR_NAME} is already in this project, and Privatier did not make it. "
                "It may hold your own files, so it was left alone. Please rename it, then try again."
            )
    folder.mkdir(exist_ok=True)
    (folder / MARKER_FILE).touch()
    return folder


__all__ = [
    "KEY_DIR_NAME", "MARKER_FILE", "PRIVATIER_DIR_NAME", "RESTORED_DIR_NAME", "PrivatierFolderError",
    "ensure_privatier_dir", "is_marked", "key_dir", "marked_folder_above", "privatier_dir", "restored_dir",
]
