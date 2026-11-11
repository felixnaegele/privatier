"""The app's logic, without the window: what the screen asks for and gets back."""

import csv
from pathlib import Path

import pytest

from privatier.app.service import AppSession

PASSWORD = "correct horse"


@pytest.fixture
def study(tmp_path: Path) -> Path:
    folder = tmp_path / "Studie"
    folder.mkdir()
    with (folder / "patients.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Name", "Geburtsdatum", "Patient ID", "Diagnosis", "Comment"])
        w.writerow(["Max Müller", "12.05.1961", "P-10037", "Aortic stenosis", "Referred by Frau Dr. Hofmann, uses the Edwards device"])
        w.writerow(["Anna Schmidt", "03.11.1958", "P-10038", "Mitral regurgitation", "Follow-up with Mr. Baker"])
    (folder / "letter.txt").write_text("Sehr geehrte Frau Dr. Hofmann,\nHerr Max Müller, geb. 12.05.1961, Zimmer Sonnenblick.\n", encoding="utf-8")
    (folder / "notes.txt").write_text("Plain notes about the Sonnenblick ward.\n", encoding="utf-8")
    return folder


def _all_text(folder: Path) -> str:
    return "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in sorted(folder.rglob("*")) if f.is_file())


def test_folder_from_scan_to_restore(study: Path):
    app = AppSession()
    scan = app.scan([str(study)], False)
    assert "error" not in scan and scan["single"] is False and scan["has_key"] is False
    values = {f["value"]: f for f in scan["findings"]}
    assert "Max Müller" in values and values["Max Müller"]["can_keep"] is False
    assert all(f["label"] and f["id"] for f in scan["findings"])

    result = app.export(1, PASSWORD, {}, [], [], [], [])
    assert "error" not in result, result
    copy = Path(result["output"])
    assert copy.name == "Studie_pseudonymised" and copy.parent == study.parent
    text = _all_text(copy)
    for secret in ("Müller", "Schmidt", "Hofmann", "12.05.1961", "P-10037"):
        assert secret not in text
    assert "Aortic stenosis" in text
    assert Path(result["key_dir"], "key.vault").is_file()

    info = app.restore_info([str(copy)])
    assert info["files"] == 3 and info["suggested_key"] == str(Path(result["key_dir"], "key.vault"))
    assert "error" in app.restore([str(copy)], info["suggested_key"], "not the password")
    assert "error" in app.restore([str(copy)], str(study / "notes.txt"), PASSWORD)
    back = app.restore([str(copy)], info["suggested_key"], PASSWORD)
    assert "error" not in back and back["restored"] == 3 and back["values"] > 0
    restored = _all_text(Path(back["output"]))
    assert "Max Müller" in restored and "Frau Dr. Hofmann" in restored
    # A second run on the same folder knows the key, and never overwrites the first copy.
    again = app.scan([str(study)], False)
    assert again["has_key"] is True
    assert Path(app.export(1, PASSWORD, {}, [], [], [], [])["output"]).name == "Studie_pseudonymised_2"


def test_keeping_a_value_and_adding_a_word(study: Path):
    app = AppSession()
    scan = app.scan([str(study)], False)
    hofmann = next(f for f in scan["findings"] if "Hofmann" in f["value"] and f["can_keep"])
    scan = app.review([hofmann["id"]], ["Sonnenblick", " ", "x"])
    added = [f for f in scan["findings"] if f["source"] == "added"]
    assert [f["value"] for f in added] == ["Sonnenblick"] and added[0]["count"] == 2
    assert next(f for f in scan["findings"] if f["id"] == hofmann["id"])["kept"] is True

    result = app.export(1, PASSWORD, {}, [], [], [hofmann["id"]], ["Sonnenblick"])
    assert "error" not in result, result
    text = _all_text(Path(result["output"]))
    assert "Hofmann" in text and "Sonnenblick" not in text and "TERM_0001" in text and "Müller" not in text
    assert result["kept"] >= 1


def test_single_file(study: Path):
    app = AppSession()
    scan = app.scan([str(study / "patients.csv")], False)
    assert "error" not in scan and scan["single"] is True and scan["folder"] == "patients.csv"
    result = app.export(1, PASSWORD, {}, [], [], [], [])
    assert "error" not in result, result
    copy = Path(result["output"])
    assert copy == study / "patients_pseudonymised"
    assert [f.name for f in copy.iterdir()] == ["patients.csv"]
    assert Path(result["key_dir"]) == study / "patients_privatier"
    back = app.restore([str(copy / "patients.csv")], str(Path(result["key_dir"], "key.vault")), PASSWORD)
    assert "error" not in back
    assert "Max Müller" in _all_text(Path(back["output"]))


def test_what_cannot_be_chosen(study: Path, tmp_path: Path):
    app = AppSession()
    other = tmp_path / "other.txt"
    other.write_text("x", encoding="utf-8")
    assert "error" in app.scan([str(study), str(other)], False)
    assert "error" in app.scan([str(study / "letter.txt"), str(other)], False)
    assert "error" in app.scan([str(tmp_path / "missing")], False)
    picture = study / "scan.png"
    picture.write_bytes(b"\x89PNG")
    assert "error" in app.scan([str(picture)], False)
