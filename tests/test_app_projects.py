"""The list of project folders the app may work in."""

from pathlib import Path

import pytest

from privatier.app.projects import ProjectStore


def test_add_list_remove_and_remember(tmp_path: Path):
    file = tmp_path / "settings" / "projects.json"
    study = tmp_path / "Studie"
    study.mkdir()
    store = ProjectStore(file)
    assert store.listing() == []
    first = store.add(study)
    assert store.add(str(study)) == first  # the same folder is not listed twice
    assert store.listing() == [{"id": first, "name": "Studie", "path": str(study.resolve()), "available": True}]
    assert store.path(first) == study.resolve()

    again = ProjectStore(file)  # the next start of the app
    assert again.listing() == store.listing()

    again.remove(first)
    assert ProjectStore(file).listing() == []
    assert study.is_dir()  # removing from the list deletes nothing


def test_a_folder_that_is_gone_is_shown_as_unavailable(tmp_path: Path):
    file = tmp_path / "projects.json"
    study = tmp_path / "Studie"
    study.mkdir()
    first = ProjectStore(file).add(study)
    study.rmdir()
    gone = ProjectStore(file)
    assert gone.listing()[0]["available"] is False and gone.path(first) is None


def test_only_folders_can_be_added(tmp_path: Path):
    file = tmp_path / "a.txt"
    file.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        ProjectStore(tmp_path / "p.json").add(file)
