"""The app's logic, without the window: what the screen asks for and gets back."""

import csv
from pathlib import Path

import pytest

from privatier.app.projects import ProjectStore
from privatier.app.service import AppSession

PASSWORD = "correct horse"


@pytest.fixture
def study(tmp_path: Path) -> Path:
    folder = tmp_path / "Studie"
    (folder / "letters").mkdir(parents=True)
    with (folder / "patients.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Name", "Geburtsdatum", "Patient ID", "Diagnosis", "Comment"])
        w.writerow(["Max Müller", "12.05.1961", "P-10037", "Aortic stenosis", "Referred by Frau Dr. Hofmann, uses the Edwards device"])
        w.writerow(["Anna Schmidt", "03.11.1958", "P-10038", "Mitral regurgitation", "Follow-up with Mr. Baker"])
    (folder / "letters" / "letter.txt").write_text("Sehr geehrte Frau Dr. Hofmann,\nHerr Max Müller, geb. 12.05.1961, Zimmer Sonnenblick.\n", encoding="utf-8")
    (folder / "notes.txt").write_text("Plain notes about the Sonnenblick ward, signed Mr. Baker.\n", encoding="utf-8")
    (folder / "scan.png").write_bytes(b"\x89PNG")
    return folder


@pytest.fixture
def app(tmp_path: Path) -> AppSession:
    return AppSession(ProjectStore(tmp_path / "app_settings" / "projects.json"))


def _open(app: AppSession, study: Path) -> dict:
    added = app.add_project([str(study)])
    assert "error" not in added and [p["name"] for p in added["projects"]] == ["Studie"]
    scan = app.open_project(added["added"], False)
    assert "error" not in scan, scan
    return scan


def _all_text(folder: Path) -> str:
    return "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in sorted(folder.rglob("*")) if f.is_file())


def test_project_from_opening_to_restore(app: AppSession, study: Path):
    scan = _open(app, study)
    assert scan["has_key"] is False and scan["folder"] == "Studie"
    files = {f["path"]: f for f in scan["files"]}
    assert set(files) == {"patients.csv", "letters/letter.txt", "notes.txt", "scan.png"}
    assert files["patients.csv"]["kind"] == "table" and files["patients.csv"]["found"] > 0
    assert files["scan.png"]["status"] == "left_out" and files["scan.png"]["selected"] is False
    values = {f["value"]: f for f in scan["findings"]}
    assert values["Max Müller"]["can_keep"] is True and values["Max Müller"]["becomes"] == "a name code"
    assert all(set(f["files"]) <= set(files) for f in scan["findings"])

    result = app.export(1, PASSWORD, {}, [], [], [], [])
    assert "error" not in result, result
    copy = Path(result["output"])
    assert copy == study / "Privatier" / "Studie_pseudonymised" and result["output_name"] == copy.name
    assert Path(result["key_dir"]) == study / "Privatier" / "Key - keep private"
    assert Path(result["key_dir"], "key.vault").is_file()
    text = _all_text(copy)
    for secret in ("Müller", "Schmidt", "Hofmann", "12.05.1961", "P-10037"):
        assert secret not in text
    assert "Aortic stenosis" in text and (copy / "letters" / "letter.txt").is_file()

    # Opened again, the project shows the same files: what Privatier made is not read as data.
    again = app.open_project(app.projects()[0]["id"], False)
    assert again["has_key"] is True and {f["path"] for f in again["files"]} == set(files)
    assert Path(app.export(1, PASSWORD, {}, [], [], [], [])["output"]).name == "Studie_pseudonymised_2"
    assert "error" in app.export(1, "another password", {}, [], [], [], [])

    assert app.restore_info([str(copy)])["files"] == 3
    assert "error" in app.restore([str(copy)], "not the password")
    back = app.restore([str(copy)], PASSWORD)
    assert "error" not in back and back["restored"] == 3 and back["values"] > 0
    restored = Path(back["output"])
    assert restored == study / "Privatier" / "Restored" / "Studie_pseudonymised_restored"
    assert "Max Müller" in _all_text(restored) and "Frau Dr. Hofmann" in _all_text(restored)


def test_keeping_a_value_and_adding_a_word(app: AppSession, study: Path):
    scan = _open(app, study)
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


def test_unticked_files_are_not_read_and_not_copied(app: AppSession, study: Path):
    _open(app, study)
    assert "error" in app.set_files([])
    assert "error" in app.set_files(["scan.png"])
    scan = app.review([], ["Sonnenblick"])
    scan = app.set_files(["notes.txt"])
    files = {f["path"]: f for f in scan["files"]}
    assert files["notes.txt"]["selected"] and not files["patients.csv"]["selected"] and files["patients.csv"]["found"] == 0
    assert not any("Müller" in f["value"] for f in scan["findings"]), "a file that is not ticked is no evidence"
    assert [f["count"] for f in scan["findings"] if f["source"] == "added"] == [1], "added words survive the new selection"
    result = app.export(1, PASSWORD, {}, [], [], [], ["Sonnenblick"])
    assert [f.name for f in Path(result["output"]).rglob("*") if f.is_file()] == ["notes.txt"]
    everything = app.set_files(["notes.txt", "patients.csv", "letters/letter.txt"])
    assert all(f["selected"] for f in everything["files"] if f["status"] == "ready")


def test_restore_needs_a_key_and_a_reachable_project(app: AppSession, study: Path):
    assert "error" in app.restore([str(study)], PASSWORD)  # nothing is open
    _open(app, study)
    assert "no key" in app.restore([str(study)], PASSWORD)["error"]
    assert app.export(3, "", {}, [], [], [], [])["key_dir"] is None
    assert "no key" in app.restore([str(study)], PASSWORD)["error"], "levels 3 and 4 keep no key"


def test_what_cannot_be_a_project(app: AppSession, study: Path, tmp_path: Path):
    assert "error" in app.add_project([str(study / "notes.txt")])
    assert "error" in app.add_project([str(study), str(tmp_path)])
    assert "error" in app.open_project("unknown", False)
    project = app.add_project([str(study)])["added"]
    assert app.remove_project(project) == {"projects": []} and study.is_dir()


def test_a_folder_named_privatier_that_is_the_users_own_is_not_taken_over(app: AppSession, study: Path):
    (study / "Privatier").mkdir()
    (study / "Privatier" / "mine.txt").write_text("my own notes", encoding="utf-8")
    _open(app, study)
    assert "error" in app.export(1, PASSWORD, {}, [], [], [], [])
    assert (study / "Privatier" / "mine.txt").read_text(encoding="utf-8") == "my own notes"


def test_each_file_is_shown_as_its_columns_and_a_column_can_be_changed(tmp_path):
    study = tmp_path / "Studie"
    study.mkdir()
    (study / "patienten.csv").write_text(
        "Patienten-ID;Nachname;Geburtsdatum;HbA1c\nP-001;Müller;03.04.1961;6,1\nP-002;Schmidt;12.05.1975;7,4\n",
        encoding="utf-8",
    )
    app = AppSession(ProjectStore(tmp_path / "settings" / "projects.json"))
    scan = app.open_project(app.add_project([str(study)])["added"], False)
    columns = scan["outline"]["patienten.csv"]["tables"][0]["columns"]
    assert [c["header"] for c in columns] == ["Patienten-ID", "Nachname", "Geburtsdatum", "HbA1c"]  # one row per column
    assert [c["kind"] for c in columns] == ["ID", "PERSON", "BIRTH_DATE", "KEEP"]
    assert all(f["can_keep"] for f in scan["findings"])  # a tickbox for every value
    by_id = {f["id"]: f["value"] for f in scan["findings"]}
    assert sorted(by_id[v["id"]] for v in columns[1]["values"]) == ["Müller", "Schmidt"]

    scan = app.set_column(columns[1]["ref"], "KEEP")  # the user says: surnames are not identifying here
    name = scan["outline"]["patienten.csv"]["tables"][0]["columns"][1]
    assert (name["kind"], name["decided"], name["values"]) == ("KEEP", "KEEP", [])
    done = app.export(1, "a long password", {}, [], [])
    written = (Path(done["output"]) / "patienten.csv").read_text(encoding="utf-8")
    assert "Müller" in written and "P-001" not in written

    scan = app.set_column(columns[1]["ref"], None)  # and takes it back
    assert scan["outline"]["patienten.csv"]["tables"][0]["columns"][1]["kind"] == "PERSON"


def test_a_column_nothing_is_done_to_can_be_ticked_to_replace(tmp_path):
    study = tmp_path / "Studie"
    study.mkdir()
    (study / "echo.csv").write_text(
        "Patienten-ID;OP-Datum;GLS\nP-001;03.04.2020;-18,5\nP-002;12.05.2021;-21,0\nP-003;01.02.2022;-16,2\n",
        encoding="utf-8",
    )
    app = AppSession(ProjectStore(tmp_path / "settings" / "projects.json"))
    scan = app.open_project(app.add_project([str(study)])["added"], False)
    gls, surgery = scan["outline"]["echo.csv"]["tables"][0]["columns"][2], scan["outline"]["echo.csv"]["tables"][0]["columns"][1]
    assert gls["kind"] == "KEEP" and not gls["tick"] and gls["total_values"] == 3

    app.set_column(surgery["ref"], "ID", True)
    scan = app.set_column(gls["ref"], "ID", True)  # the user ticks Replace on both
    columns = scan["outline"]["echo.csv"]["tables"][0]["columns"]
    assert [(c["tick"], c["kind_label"], len(c["values"])) for c in columns[1:]] == [(True, "Replaced by you", 3)] * 2
    written = (Path(app.export(1, "a long password", {}, [], [])["output"]) / "echo.csv").read_text(encoding="utf-8")
    assert "-18,5" not in written and "03.04.2020" not in written

    scan = app.set_column(gls["ref"], None)  # unticked: the column is as before
    assert scan["outline"]["echo.csv"]["tables"][0]["columns"][2]["kind"] == "KEEP"


def test_a_spot_check_finds_a_missed_value_or_says_it_is_nowhere(tmp_path):
    study = tmp_path / "Studie"
    study.mkdir()
    (study / "notes.csv").write_text("Nr;Bemerkung\n1;Befund unauffällig, Kontrolle Zaunkönig\n2;keine\n", encoding="utf-8")
    app = AppSession(ProjectStore(tmp_path / "settings" / "projects.json"))
    app.open_project(app.add_project([str(study)])["added"], False)

    nowhere = app.spot_check([], [], "Quetzalcoatl")
    assert nowhere["spot"] == {"term": "Quetzalcoatl", "found": False, "already": False}
    assert not any(f["source"] == "added" for f in nowhere["findings"])
    assert app.choice.extra == []  # a value in no file does not go on the list

    found = app.spot_check([], [], "Zaunkönig")
    assert found["spot"]["found"] and found["spot"]["places"] == 1
    assert app.choice.extra == ["Zaunkönig"]
    written = (Path(app.export(1, "a long password", {}, [], [], [], ["Zaunkönig"])["output"]) / "notes.csv").read_text(encoding="utf-8")
    assert "Zaunkönig" not in written and "Befund unauffällig" in written
