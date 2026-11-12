"""Each file as an outline of its columns, questions attached to their place, and the user's say over
every value and every column. Mock data only, in German and English."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pyreadstat
import pytest
from docx import Document
from openpyxl import Workbook, load_workbook

from privatier.engine import KEY_FILE, anonymize_folder, restore_folder, scan_folder
from privatier.identity import Decisions
from privatier.review import Review
from privatier.uniqueness import read_tables
from privatier.vault import load_vault

PASSWORD = "testpass123"
PEOPLE = [
    ("P-1001", "Anna", "Berger", dt.datetime(1975, 5, 12), "w", 48, dt.datetime(2021, 4, 3), 13.1, "Kontrolle bei Dr. Krause empfohlen"),
    ("P-1002", "Jürgen", "Müller", dt.datetime(1961, 8, 23), "m", 62, dt.datetime(2021, 5, 9), 12.2, "keine Besonderheiten im Verlauf"),
    ("P-1003", "Selin", "Öztürk", dt.datetime(1988, 1, 2), "w", 35, dt.datetime(2022, 1, 17), 14.0, "Rückruf unter 0441 5550123 erbeten"),
    ("P-1004", "Anna", "Berger", dt.datetime(1990, 7, 7), "w", 33, dt.datetime(2022, 2, 1), 11.9, "Tochter von Frau Berger begleitet"),
    ("P-1005", "Karl", "Vogel", dt.datetime(1950, 3, 3), "m", 73, dt.datetime(2022, 3, 5), 13.3, "stabil"),
]
GERMAN = ["Patient ID", "Vorname", "Nachname", "Geburtsdatum", "Geschlecht", "Alter", "OP Datum", "Hb", "Bemerkung"]
ENGLISH = ["Study ID", "Surname", "Date of birth", "Town", "Visit date", "Score", None]
TOWNS = ["Ashbury", "Kelton", "Marlow", "Ashbury", "Kelton"]


@pytest.fixture
def study(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    wb = Workbook()
    ws = wb.active
    ws.title = "Patienten"
    ws.append(GERMAN)
    for row in PEOPLE:
        ws.append(list(row))
    second = wb.create_sheet("Follow up")
    second.append(ENGLISH)
    for i, row in enumerate(PEOPLE):
        second.append([row[0], row[2], row[3], TOWNS[i], dt.datetime(2023, 1 + i, 10), 3 + i, 90000 + 17 * i])
    wb.save(folder / "daten.xlsx")
    (folder / "labor.csv").write_text(
        "Patient ID;Name;Befund;Wert\n"
        + "".join(f"{r[0]};{r[2]}, {r[1]};Labor ok, Rücksprache mit Dr. Krause;{i}.5\n" for i, r in enumerate(PEOPLE)),
        encoding="utf-8",
    )
    frame = pd.DataFrame({
        "pid": [r[0] for r in PEOPLE], "nachname": [r[2] for r in PEOPLE],
        "alter": [float(r[5]) for r in PEOPLE], "score": [1.0, 2.0, 3.0, 2.0, 1.0],
    })
    pyreadstat.write_sav(frame, str(folder / "fragebogen.sav"), column_labels=["Patienten-ID", "Nachname", "Alter in Jahren", "Score"])
    doc = Document()
    doc.add_paragraph("Arztbrief über Frau Anna Berger, geb. 12.05.1975. Operation am 03.04.2021 im Klinikum Lindenhof.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Fallnummer", "F-2021-0042"
    table.cell(1, 0).text, table.cell(1, 1).text = "Name", "Berger, Anna"
    doc.save(folder / "brief.docx")
    return folder


def outline_of(scan, file, table=None):
    one = next(f for f in scan.outline if f.file == file)
    return one if table is None else next(t for t in one.tables if t.name == table)


def sheet(path: Path, name: str) -> list[dict]:
    rows = list(load_workbook(path, data_only=True)[name].iter_rows(values_only=True))
    return [dict(zip(rows[0], r)) for r in rows[1:]]


def finding(scan, value, type_):
    return next(f for f in scan.findings if f.value == value and f.type == type_)


def test_every_column_is_listed_with_what_it_is_and_what_is_found_in_it(study):
    scan = scan_folder(study)
    by_id = {f.id: f for f in scan.findings}
    assert [f.file for f in scan.outline] == ["brief.docx", "daten.xlsx", "fragebogen.sav", "labor.csv"]

    german = outline_of(scan, "daten.xlsx", "Patienten")
    assert [c.header for c in german.columns] == GERMAN, "one entry per column of the file, in its order"
    assert [c.kind for c in german.columns] == ["ID", "PERSON", "PERSON", "BIRTH_DATE", "SEX", "AGE", "DATE", "PLAIN", "TEXT"]
    assert [c.ref for c in german.columns] == [("daten.xlsx", "Patienten", i) for i in range(9)]
    assert all(c.total_values == 5 and c.decided is None for c in german.columns)
    surname = german.columns[2]
    assert surname.becomes == "a name code (PERSON_…)"
    assert {(by_id[i].value, n) for i, n in surname.values} == {("Berger", 2), ("Müller", 1), ("Öztürk", 1), ("Vogel", 1)}
    assert german.columns[3].becomes == "the year only" and len(german.columns[3].values) == 5
    assert german.columns[7].values == [] and german.columns[7].becomes == "stays as it is"
    assert german.columns[6].becomes.startswith("dates stay")
    assert {by_id[i].type for i, _ in german.columns[8].values} == {"PERSON", "PHONE"}, "what is found inside free text"

    english = outline_of(scan, "daten.xlsx", "Follow up")
    assert [c.header for c in english.columns] == [*ENGLISH[:6], "(column 7)"]
    assert [c.kind for c in english.columns] == ["ID", "PERSON", "BIRTH_DATE", "ADDRESS", "DATE", "PLAIN", "ID"]
    assert english.columns[6].becomes == "an ID code (ID_…)", "no header and a different number in every row"

    assert [c.kind for c in outline_of(scan, "labor.csv", "").columns] == ["ID", "PERSON", "TEXT", "PLAIN"]
    spss = outline_of(scan, "fragebogen.sav", "")
    assert [(c.header, c.kind) for c in spss.columns] == [("pid", "ID"), ("nachname", "PERSON"), ("alter", "AGE"), ("score", "PLAIN")]

    letter = outline_of(scan, "brief.docx")
    assert letter.tables == [], "a Word table is not a table of rows: what is in it is listed by type"
    groups = {kind: {(by_id[i].value, n) for i, n in items} for kind, items in letter.groups}
    assert set(groups) == {"DATE", "ID", "ORG", "PERSON"} and ("F-2021-0042", 1) in groups["ID"]
    assert outline_of(scan, "daten.xlsx").groups == []

    # Every place a finding is counted in adds up to the finding.
    total: dict[str, int] = {}
    for file in scan.outline:
        places = [c.values for t in file.tables for c in t.columns] + [items for _, items in file.groups]
        for items in places:
            for i, n in items:
                total[i] = total.get(i, 0) + n
    assert total == {f.id: f.count for f in scan.findings}


def test_a_question_says_which_column_and_which_values_it_is_about(study, tmp_path):
    scan = scan_folder(study)
    by_id = {f.id: f for f in scan.findings}
    columns = [q for q in scan.questions if q.kind == "column"]
    assert {next(iter(q.columns)) for q in columns} >= {("daten.xlsx", "Follow up", 6)}
    assert all(q.columns == {q.payload} for q in columns)
    mention = next(q for q in scan.questions if q.kind == "mention")
    assert mention.columns == {("daten.xlsx", "Patienten", 8)}
    assert {by_id[i].value for i in mention.finding_ids} == {"Berger"}

    folder = tmp_path / "Study"
    folder.mkdir()
    for name in ("a.csv", "b.csv"):
        (folder / name).write_text("First name,Surname,Score\nGrace,White,3\nOwen,Hughes,4\n", encoding="utf-8")
    again = scan_folder(folder)
    names = {f.id: f.value for f in again.findings}
    same = next(q for q in again.questions if q.kind == "same_name")
    assert same.columns == {(file, "", i) for file in ("a.csv", "b.csv") for i in (0, 1)}
    assert {names[i] for i in same.finding_ids if i in names} in ({"Grace", "White"}, {"Owen", "Hughes"})


def test_any_value_can_be_kept_also_in_an_identifying_column(study, tmp_path):
    scan = scan_folder(study)
    assert all(f.can_keep for f in scan.findings)
    keep = {finding(scan, "Berger", "PERSON").id, finding(scan, "1961-08-23", "BIRTH_DATE").id, finding(scan, "P-1003", "ID").id}
    review = Review(keep=keep)
    summary = anonymize_folder(study, PASSWORD, review=review)
    rows = sheet(summary.output_dir / "daten.xlsx", "Patienten")
    plain = anonymize_folder(study, PASSWORD, output_dir=tmp_path / "plain", key_dir=tmp_path / "plain_key")
    before = sheet(plain.output_dir / "daten.xlsx", "Patienten")

    assert rows[0]["Nachname"] == "Berger" and rows[3]["Nachname"] == "Berger", "the cell stays as written"
    assert rows[0]["Vorname"].startswith("PERSON_") and rows[0]["Vorname"] != rows[3]["Vorname"], "two people still"
    assert rows[0]["Patient ID"].startswith("ID_") and rows[0]["Geburtsdatum"] == 1975
    assert rows[1]["Geburtsdatum"] == dt.datetime(1961, 8, 23), "a kept birth date stays in full"
    assert rows[1]["Nachname"].startswith("PERSON_") and rows[2]["Patient ID"] == "P-1003"
    assert rows[3]["Bemerkung"] == "Tochter von Frau Berger begleitet", "and stays wherever else it is written"
    for kept, usual in zip(rows, before):  # nothing else changes kind
        assert all(kept[h] == usual[h] for h in ("Geschlecht", "Alter", "OP Datum", "Hb"))
    assert sheet(summary.output_dir / "daten.xlsx", "Follow up")[2]["Study ID"] == "P-1003"
    assert "Berger;" not in (summary.output_dir / "labor.csv").read_text(encoding="utf-8"), "another value: 'Berger, Anna'"
    spss, _ = pyreadstat.read_sav(str(summary.output_dir / "fragebogen.sav"))
    assert list(spss["pid"])[2] == "P-1003" and list(spss["nachname"])[0] == "Berger" and str(spss["pid"][0]).startswith("ID_")

    key = load_vault(summary.key_dir / KEY_FILE, PASSWORD)
    assert not any(e["original"] == "P-1003" for e in key["entries"]), "a kept ID is not in the key"
    assert summary.kept_values == 3 and summary.kept_places > 3
    restored = restore_folder(summary.output_dir, summary.key_dir / KEY_FILE, PASSWORD)
    back = sheet(restored.output_dir / "daten.xlsx", "Patienten")
    assert [(r["Patient ID"], r["Vorname"], r["Nachname"]) for r in back] == [(p[0], p[1], p[2]) for p in PEOPLE]
    assert back[1]["Geburtsdatum"] == dt.datetime(1961, 8, 23)

    seen = scan_folder(study, review=review)
    assert finding(seen, "Berger", "PERSON").kept and finding(seen, "Berger", "PERSON").becomes == "kept as written"
    assert not finding(seen, "Müller", "PERSON").kept


def crowd(n=40):
    rows = [["Patient ID", "Geschlecht", "Alter", "Station", "Hb"]]
    for i in range(n):
        rows.append([f"P{i:04d}", "m" if i % 2 else "w", 60 + i % 5, "Nord" if i % 2 else "West", 10.5 + i])
    return rows


def write_rows(path: Path, rows: list[list]) -> None:
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    wb.save(path)


def test_a_kept_value_or_column_never_earns_the_word_anonymous(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    write_rows(folder / "a.xlsx", crowd())
    scan = scan_folder(folder)
    out = lambda name: {"output_dir": tmp_path / name, "key_dir": tmp_path / f"{name}_key"}  # noqa: E731
    assert anonymize_folder(folder, level=4, **out("plain")).verdict.anonymous

    one = anonymize_folder(folder, level=4, review=Review(keep={finding(scan, "P0007", "ID").id}), **out("one"))
    assert sheet(one.output_dir / "a.xlsx", "Sheet")[7]["Patient ID"] == "P0007"
    assert not one.verdict.anonymous and any("marked as not sensitive" in r for r in one.verdict.reasons)

    column = Decisions(columns={("a.xlsx", "Sheet", 0): "KEEP"})
    whole = anonymize_folder(folder, level=4, decisions=column, **out("whole"))
    assert [r["Patient ID"] for r in sheet(whole.output_dir / "a.xlsx", "Sheet")][:2] == ["P0000", "P0001"]
    assert not whole.verdict.anonymous and any("chose to keep Patient ID" in r for r in whole.verdict.reasons)

    numbers = Decisions(columns={("a.xlsx", "Sheet", 4): "KEEP"})  # a measurement was never changed anyway
    assert anonymize_folder(folder, level=4, decisions=numbers, **out("numbers")).verdict.anonymous


def test_the_user_can_say_what_any_column_is(study):
    decisions = Decisions(columns={
        ("daten.xlsx", "Patienten", 2): "KEEP",  # a name column: leave it alone
        ("daten.xlsx", "Patienten", 8): "PERSON",  # free text: replace every cell
        ("daten.xlsx", "Patienten", 7): "ID",  # a number column
        ("daten.xlsx", "Follow up", 4): "DOB",  # a date column: these are birth dates
        ("daten.xlsx", "Follow up", 2): "KEEP_DATES",  # called a birth date, but holds other dates
        ("labor.csv", "", 1): "KEEP",
        ("labor.csv", "", 2): "KEEP",
        ("fragebogen.sav", "", 3): "ID",
    })
    scan = scan_folder(study, decisions=decisions)
    german = outline_of(scan, "daten.xlsx", "Patienten").columns
    assert [(c.kind, c.decided) for c in (german[2], german[7], german[8])] == [("PLAIN", "KEEP"), ("ID", "ID"), ("PERSON", "PERSON")]
    assert german[2].values == [] and len(german[8].values) == 5 and len(german[7].values) == 5
    english = outline_of(scan, "daten.xlsx", "Follow up").columns
    assert [(c.kind, c.decided) for c in (english[2], english[4])] == [("DATE", "KEEP_DATES"), ("BIRTH_DATE", "DOB")]
    assert outline_of(scan, "fragebogen.sav", "").columns[3].kind == "ID"
    assert all(c.decided not in c.choices for t in outline_of(scan, "daten.xlsx").tables for c in t.columns)

    tables = {(t.file, t.name): t for t in read_tables(study, decisions.columns)[0]}
    assert tables[("daten.xlsx", "Patienten")].columns[2].kept and tables[("daten.xlsx", "Patienten")].columns[2].patient is None
    assert tables[("daten.xlsx", "Patienten")].columns[7].patient == "id"
    assert tables[("daten.xlsx", "Follow up")].columns[4].kind == "birth"
    assert tables[("daten.xlsx", "Follow up")].columns[2].kind == "date"

    summary = anonymize_folder(study, PASSWORD, decisions=decisions)
    rows = sheet(summary.output_dir / "daten.xlsx", "Patienten")
    assert [r["Nachname"] for r in rows] == [p[2] for p in PEOPLE], "left alone"
    assert all(r["Bemerkung"].startswith("PERSON_") and r["Hb"].startswith("ID_") for r in rows)
    assert all(r["Patient ID"].startswith("ID_") and r["Vorname"].startswith("PERSON_") for r in rows)
    follow = sheet(summary.output_dir / "daten.xlsx", "Follow up")
    assert [r["Visit date"] for r in follow] == [2023] * 5 and follow[0]["Date of birth"] == dt.datetime(1975, 5, 12)
    lines = (summary.output_dir / "labor.csv").read_text(encoding="utf-8").splitlines()
    assert lines[1].split(";")[1:3] == ["Berger, Anna", "Labor ok, Rücksprache mit Dr. Krause"], "nothing is looked for in it"
    assert lines[1].startswith("ID_")
    spss, _ = pyreadstat.read_sav(str(summary.output_dir / "fragebogen.sav"))
    assert all(str(v).startswith("ID_") for v in spss["score"])
