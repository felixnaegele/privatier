"""Privatier's own folder inside the project: never read, never mistaken for the user's data. Mock data only."""

from __future__ import annotations

from pathlib import Path

import pytest

from privatier.engine import AUDIT_FILE, KEY_FILE, REPORT_FILE, anonymize_folder, restore_folder, scan_folder
from privatier.project import (
    KEY_DIR_NAME, MARKER_FILE, PRIVATIER_DIR_NAME, PrivatierFolderError, ensure_privatier_dir, key_dir,
    privatier_dir, restored_dir,
)
from privatier.review import Review
from privatier.uniqueness import list_files, read_tables

from test_review import GERMAN_LETTER, GERMAN_ROWS, by_value, make

PASSWORD = "testpass123"
FILES = ["data.xlsx", "letters/letter.txt"]


@pytest.fixture
def project(tmp_path):
    return make(tmp_path, GERMAN_ROWS, GERMAN_LETTER)


def names(folder: Path) -> list[str]:
    return [str(p.relative_to(folder)) for p in list_files(folder)]


def test_the_folder_is_made_once_and_never_taken_from_the_user(project):
    folder = ensure_privatier_dir(project)
    assert folder == privatier_dir(project) == project / PRIVATIER_DIR_NAME and (folder / MARKER_FILE).is_file()
    assert ensure_privatier_dir(project) == folder, "asking again changes nothing"
    assert key_dir(project) == folder / KEY_DIR_NAME and restored_dir(project).parent == folder

    theirs = make(project.parent, GERMAN_ROWS, GERMAN_LETTER, "Other")
    (theirs / PRIVATIER_DIR_NAME).mkdir()
    (theirs / PRIVATIER_DIR_NAME / "own_notes.txt").write_text("Frau Anna Berger, geb. 12.05.1975", encoding="utf-8")
    with pytest.raises(PrivatierFolderError):
        ensure_privatier_dir(theirs)
    assert not (theirs / PRIVATIER_DIR_NAME / MARKER_FILE).exists()
    assert f"{PRIVATIER_DIR_NAME}/own_notes.txt" in names(theirs), "without the marker it is data like any other"
    with pytest.raises(ValueError):  # and nothing may be written into it
        anonymize_folder(theirs, PASSWORD, output_dir=theirs / PRIVATIER_DIR_NAME / "copy", key_dir=theirs.parent / "k")

    empty = make(project.parent, GERMAN_ROWS, GERMAN_LETTER, "Third")
    (empty / PRIVATIER_DIR_NAME).mkdir()
    (empty / PRIVATIER_DIR_NAME / ".DS_Store").write_bytes(b"")
    assert (ensure_privatier_dir(empty) / MARKER_FILE).is_file(), "an empty folder of that name can be used"


def test_copies_key_and_restored_results_live_in_the_project_and_are_never_read(project, tmp_path):
    own = ensure_privatier_dir(project)
    first = anonymize_folder(project, PASSWORD, output_dir=own / "Studie_pseudonymised", key_dir=key_dir(project))
    assert first.processed == FILES and first.skipped == [] and first.key_dir == key_dir(project)
    assert {p.name for p in key_dir(project).iterdir()} == {KEY_FILE, AUDIT_FILE, REPORT_FILE}
    assert names(project) == FILES, "the copy and the key are not part of the project's data"

    # A second run reads the same two files, and the key gives the same codes.
    second = anonymize_folder(project, PASSWORD, output_dir=own / "Studie_pseudonymised_2", key_dir=key_dir(project))
    assert second.processed == FILES and second.skipped == [] and second.errors == []
    letter = "letters/letter.txt"
    assert (second.output_dir / letter).read_text(encoding="utf-8") == (first.output_dir / letter).read_text(encoding="utf-8")
    assert "PERSON_0001" in (second.output_dir / letter).read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        anonymize_folder(project, PASSWORD, output_dir=own / "Studie_pseudonymised", key_dir=key_dir(project))
    with pytest.raises(ValueError):
        anonymize_folder(project, PASSWORD, output_dir=key_dir(project) / "copy", key_dir=key_dir(project))
    with pytest.raises(ValueError):  # inside the project, but not in Privatier's folder
        anonymize_folder(project, PASSWORD, output_dir=project / "letters" / "copy", key_dir=key_dir(project))

    # Results from the AI can come from anywhere, and from the copy itself.
    results = tmp_path / "from_the_ai"
    results.mkdir()
    (results / "summary.md").write_text("PERSON_0001 was operated on DATE_0002.", encoding="utf-8")
    back = restore_folder(results, key_dir(project) / KEY_FILE, PASSWORD, output_dir=restored_dir(project) / "from_the_ai_restored")
    assert (back.output_dir / "summary.md").read_text(encoding="utf-8") == "Anna Berger was operated on 03.04.2021."
    whole = restore_folder(first.output_dir, key_dir(project) / KEY_FILE, PASSWORD, output_dir=restored_dir(project) / "copy_restored")
    assert (whole.output_dir / letter).read_text(encoding="utf-8") == GERMAN_LETTER
    with pytest.raises(ValueError):  # real values must not land between the coded files
        restore_folder(results, key_dir(project) / KEY_FILE, PASSWORD, output_dir=results / "restored")

    # With real names back inside the project, nothing of it is read, counted or used as evidence.
    scan = scan_folder(project)
    assert {f for finding in scan.findings for f in finding.files} == set(FILES)
    assert scan.other_files == [letter] and scan.unsupported == [] and scan.named_files == []
    assert [t.file for t in read_tables(project)[0]] == ["data.xlsx"]
    third = anonymize_folder(project, PASSWORD, output_dir=own / "Studie_pseudonymised_3", key_dir=key_dir(project))
    assert third.processed == FILES and third.skipped == []


def test_what_a_finding_becomes_and_which_file_it_belongs_to(tmp_path):
    folder = make(tmp_path, GERMAN_ROWS, GERMAN_LETTER)
    (folder / "letters" / "a.txt").write_text("Seen by Mr Arthur Finch, born 04.05.1950, last week.\n", encoding="utf-8")
    (folder / "letters" / "b.txt").write_text("Mr Arthur Finch called again.\n", encoding="utf-8")
    scan = scan_folder(folder, review=Review(extra=["Zeppelin"]))
    files = set(names(folder))
    assert scan.questions and all(q.files and q.files <= files for q in scan.questions), "paths as the scan lists them"
    assert all(set(f.files) <= files for f in scan.findings)
    assert "letters/b.txt" in {f for q in scan.questions for f in q.files}, "also for a file in a subfolder"
    assert by_value(scan.findings, "Anna Berger").becomes == "a name code (PERSON_…)"
    assert by_value(scan.findings, "P-1001").becomes == "an ID code (ID_…)"
    assert by_value(scan.findings, "1975-05-12").becomes == "the year 1975"
    assert by_value(scan.findings, "Zeppelin").becomes == "nothing: this word was not found"
    assert all(f.becomes for f in scan.findings)
    clinic = by_value(scan.findings, "Klinikum Lindenhof")
    kept = scan_folder(folder, review=Review(keep={clinic.id}))
    assert by_value(kept.findings, "Klinikum Lindenhof").becomes == "kept as written"
