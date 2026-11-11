"""The review screen's side of the engine: what would be replaced, what the user keeps or adds, and single files.

Mock data only, in German and English.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from privatier.engine import AUDIT_FILE, KEY_FILE, REPORT_FILE, anonymize_folder, restore_folder, scan_folder
from privatier.pseudonyms import TOKEN_RE
from privatier.review import Review, finding_id
from privatier.uniqueness import read_tables
from privatier.vault import load_vault

PASSWORD = "testpass123"

GERMAN_ROWS = [
    ["Patient ID", "Vorname", "Nachname", "Geburtsdatum", "Wohnort", "Hb", "Bemerkung"],
    ["P-1001", "Anna", "Berger", dt.datetime(1975, 5, 12), "Sonnental", 13.1, "Kontrolle bei Dr. Krause, Hausarzt Dr. Tobias Winter informiert"],
    ["P-1002", "Jürgen", "Müller", dt.datetime(1961, 8, 23), "Oldenburg", 12.2, "keine Besonderheiten"],
    ["P-1003", "Selin", "Öztürk", dt.datetime(1988, 1, 2), "Bremen", 14.0, "Rückruf unter 0441 5550123 erbeten"],
]
GERMAN_LETTER = (
    "Sehr geehrter Herr Dr. Krause,\n\n"
    "wir berichten über Frau Anna Berger, geb. 12.05.1975, wohnhaft in Sonnental.\n"
    "Die Patientin wurde am 03.04.2021 im Klinikum Lindenhof operiert.\n"
    "Rückfragen an Dr. Tobias Winter, winter@praxis-winter.example, Tel. 0441 5550123.\n"
    "Die Teilnahme an der LUMINA-Studie wurde besprochen. Herr Mueller aus Oldenburg war Zimmernachbar.\n"
    "Die Pflege auf Station Lumina übernahm Schwester Gruenwald.\n"
    "Abrechnung über das Projekt hoefler.\n"
)
ENGLISH_ROWS = [
    ["Study ID", "First name", "Surname", "Date of birth", "Town", "Hb", "Notes"],
    ["S-2001", "Grace", "White", dt.datetime(1970, 3, 9), "Ashbury", 12.9, "Seen by Dr. Patel, GP Dr. Helen Marsh informed"],
    ["S-2002", "Owen", "Hughes", dt.datetime(1958, 11, 30), "Kelton", 13.4, "nothing of note"],
    ["S-2003", "Priya", "Nair", dt.datetime(1991, 6, 17), "Marlow", 11.8, "call back on 020 7946 0123"],
]
ENGLISH_LETTER = (
    "Dear Dr. Patel,\n\n"
    "We are writing about Mrs Grace White, born 09/03/1970, who lives in Ashbury.\n"
    "She had surgery on 14/02/2022 at Riverside Hospital.\n"
    "Questions to Dr. Helen Marsh, marsh@surgery-marsh.example.\n"
    "Taking part in the HALCYON trial was discussed. The Halcyon nurse will call.\n"
)


def write_xlsx(path: Path, rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)


def make(tmp_path: Path, rows: list[list], letter: str, name: str = "Studie") -> Path:
    folder = tmp_path / name
    (folder / "letters").mkdir(parents=True)
    write_xlsx(folder / "data.xlsx", rows)
    (folder / "letters" / "letter.txt").write_text(letter, encoding="utf-8")
    return folder


@pytest.fixture
def german(tmp_path):
    return make(tmp_path, GERMAN_ROWS, GERMAN_LETTER)


@pytest.fixture
def english(tmp_path):
    return make(tmp_path, ENGLISH_ROWS, ENGLISH_LETTER, "Study")


def all_text(folder: Path) -> str:
    """Everything a reader of the copy can see."""
    parts = []
    for path in sorted(folder.rglob("*")):
        if path.suffix == ".xlsx":
            for ws in load_workbook(path).worksheets:
                parts.extend(str(v) for row in ws.iter_rows(values_only=True) for v in row if v is not None)
        elif path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def codes_in(text: str) -> list[str]:
    out = []
    for m in TOKEN_RE.finditer(text):
        out.append(f"{m.group(1).upper()}_{m.group(2)}" + (f"_{m.group(3)}" if m.group(3) else ""))
    return out


def by_value(findings, value, type_=None):
    found = [f for f in findings if f.value == value and (type_ is None or f.type == type_)]
    assert len(found) == 1, (value, [(f.type, f.value) for f in findings])
    return found[0]


def private_files(folder: Path) -> str:
    return (folder / AUDIT_FILE).read_text(encoding="utf-8") + (folder / REPORT_FILE).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- findings
@pytest.mark.parametrize("language", ["german", "english"])
def test_the_list_shows_exactly_what_the_export_replaces(language, request, tmp_path):
    folder = request.getfixturevalue(language)
    scan = scan_folder(folder)
    summary = anonymize_folder(folder, PASSWORD)
    key = load_vault(summary.key_dir / KEY_FILE, PASSWORD)
    original = {e["token"]: (e["type"], e["original"]) for e in key["entries"]}
    ids = {f.id: f for f in scan.findings}
    assert len(ids) == len(scan.findings), "one entry per value"

    written = codes_in(all_text(summary.output_dir))
    assert written
    seen = set()
    for code in written:  # every code in the copy is in the list
        finding = ids.get(finding_id(*original[code]))
        assert finding is not None and finding.count > 0, code
        seen.add(finding.id)
    with_code = [f for f in scan.findings if f.type != "BIRTH_DATE"]
    assert {f.id for f in with_code} == seen, "and everything in the list is a code in the copy"
    assert sum(f.count for f in with_code) == len(written)
    births = [f for f in scan.findings if f.type == "BIRTH_DATE"]
    assert len(births) == 3 and sum(f.count for f in births) == summary.counts["DATE_OF_BIRTH_TO_YEAR"]
    assert all(f.source == "column" and not f.can_keep for f in births)
    assert all(f.can_keep == (f.source != "column") for f in scan.findings)
    assert {f.id for f in scan_folder(folder).findings} == set(ids), "the ids are the same in every scan"


def test_where_a_finding_comes_from(german):
    findings = scan_folder(german).findings
    town = by_value(findings, "Sonnental")
    assert town.source == "column" and not town.can_keep and town.count == 2
    assert town.files == ["data.xlsx", "letters/letter.txt"]
    assert by_value(findings, "Anna Berger").source == "column", "a name from the table, wherever it is written"
    assert by_value(findings, "Mueller").source == "column", "also without the umlaut"
    assert by_value(findings, "12.05.1975", "DATE").source == "column", "the birth date of the table, in a letter"
    clinic = by_value(findings, "Klinikum Lindenhof")
    assert clinic.source == "rule" and clinic.can_keep and clinic.type == "ORG"
    doctor = by_value(findings, "Tobias Winter")
    assert doctor.source == "rule" and doctor.count == 2 and len(doctor.files) == 2


# --------------------------------------------------------------------------- keep
def test_a_kept_value_stays_as_written_and_only_its_number_is_recorded(german, tmp_path):
    plain = anonymize_folder(german, PASSWORD, output_dir=tmp_path / "plain", key_dir=tmp_path / "plain_key")
    same = anonymize_folder(
        german, PASSWORD, output_dir=tmp_path / "same", key_dir=tmp_path / "same_key", review=Review()
    )
    assert all_text(plain.output_dir) == all_text(same.output_dir), "no choices, no change"

    findings = scan_folder(german).findings
    keep = {by_value(findings, v).id for v in ("Klinikum Lindenhof", "Tobias Winter", "Sonnental", "Anna Berger")}
    review = Review(keep=keep | {"no such id"})
    summary = anonymize_folder(german, PASSWORD, review=review)
    out = all_text(summary.output_dir)
    assert "im Klinikum Lindenhof operiert" in out
    assert out.count("Dr. Tobias Winter") == 2, "in the letter and in the free-text cell"
    assert "Sonnental" not in out and "Berger" not in out, "a value of an identifying column is replaced all the same"
    assert (summary.kept_values, summary.kept_places) == (2, 3)

    key = load_vault(summary.key_dir / KEY_FILE, PASSWORD)
    assert not any("Winter" in e["original"] or "Lindenhof" in e["original"] for e in key["entries"])
    private = private_files(summary.key_dir)
    assert "Lindenhof" not in private and "Winter" not in private
    assert not any(i in private for i in keep), "nor the ids, which are worked out from the values"
    finished = [json.loads(line) for line in (summary.key_dir / AUDIT_FILE).read_text().splitlines()][-1]
    assert finished["kept_values"] == 2 and finished["kept_places"] == 3
    assert "2 value(s)" in (summary.key_dir / REPORT_FILE).read_text()

    again = scan_folder(german, review=review).findings
    assert by_value(again, "Klinikum Lindenhof").kept and by_value(again, "Tobias Winter").count == 2
    assert not by_value(again, "Sonnental").kept
    # Everything else is replaced exactly as without the choice.
    left = {"Klinikum Lindenhof", "Tobias Winter"}
    assert {(f.type, f.value, f.count) for f in again if f.value not in left} == {
        (f.type, f.value, f.count) for f in findings if f.value not in left
    }


def test_a_kept_name_asks_nothing(tmp_path):
    folder = tmp_path / "Study"
    folder.mkdir()
    (folder / "a.txt").write_text("Seen by Mr Arthur Finch, born 04.05.1950, last week.\n", encoding="utf-8")
    (folder / "b.txt").write_text("Mr Arthur Finch called again.\n", encoding="utf-8")
    scan = scan_folder(folder)
    assert scan.questions, "the same name twice, and nothing confirms it is one person"
    review = Review(keep={by_value(scan.findings, "Arthur Finch").id})
    assert not scan_folder(folder, review=review).questions
    summary = anonymize_folder(folder, PASSWORD, review=review)
    assert (summary.output_dir / "b.txt").read_text(encoding="utf-8") == "Mr Arthur Finch called again.\n"
    assert not summary.warnings


def clinic_table(n=40):
    rows = [["Patient ID", "Geschlecht", "Alter", "Klinik", "Hb"]]
    for i in range(n):
        rows.append([f"P{i:04d}", "m" if i % 2 else "w", 60 + i % 5, "Klinikum Lindenhof", 10.5 + i])
    return rows


def test_a_kept_value_blocks_the_word_anonymous(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    write_xlsx(folder / "a.xlsx", clinic_table())
    scan = scan_folder(folder)
    clinic = by_value(scan.findings, "Klinikum Lindenhof")
    assert clinic.can_keep and clinic.count == 40

    plain = anonymize_folder(folder, level=4, output_dir=tmp_path / "plain", key_dir=tmp_path / "plain_key")
    assert plain.verdict.anonymous, plain.verdict.reasons
    kept = anonymize_folder(
        folder, level=4, output_dir=tmp_path / "kept", key_dir=tmp_path / "kept_key", review=Review(keep={clinic.id})
    )
    assert "Klinikum Lindenhof" in all_text(kept.output_dir)
    assert not kept.verdict.anonymous
    assert any("marked as not sensitive" in reason for reason in kept.verdict.reasons)
    assert "Lindenhof" not in private_files(kept.key_dir)


# --------------------------------------------------------------------------- added words
def test_an_added_word_is_replaced_everywhere_and_comes_back(german, tmp_path):
    review = Review(extra=["  lumina ", "Höfler", "Grünwald", "Zeppelin", "x", "   ", "Lumina"])
    scan = scan_folder(german, review=review)
    added = {f.value: f for f in scan.findings if f.type == "TERM"}
    assert set(added) == {"lumina", "Höfler", "Grünwald", "Zeppelin"}, "blank and one-letter words are ignored, each word once"
    assert all(f.source == "added" and not f.can_keep for f in added.values())
    assert added["lumina"].count == 2 and added["Höfler"].count == 1 and added["Zeppelin"].count == 0
    # A rule had found this name already: it stays a person, and the added word says so.
    assert (added["Grünwald"].count, added["Grünwald"].already_replaced) == (0, 1)
    assert added["Zeppelin"].already_replaced == 0
    assert added["lumina"].id == finding_id("TERM", "Lumina"), "the id does not depend on how it was typed"

    summary = anonymize_folder(german, PASSWORD, review=review)
    letter = (summary.output_dir / "letters" / "letter.txt").read_text(encoding="utf-8")
    assert "lumina" not in letter.casefold() and "Gruenwald" not in letter and "hoefler" not in letter
    assert "TERM_0001" in letter and "Station TERM_" in letter and "Projekt TERM_0002_V1." in letter
    assert "Schwester PERSON_" in letter
    assert (summary.added_terms, summary.added_found, summary.added_places) == (4, 3, 3)
    assert summary.counts["TERM"] == 3
    key = load_vault(summary.key_dir / KEY_FILE, PASSWORD)
    assert {e["type"] for e in key["entries"]} >= {"TERM"}
    assert "Zeppelin" not in str(key), "a word that occurs nowhere is not stored"
    private = private_files(summary.key_dir)
    assert "lumina" not in private.casefold() and "hoefler" not in private.casefold() and "Zeppelin" not in private

    restored = restore_folder(summary.output_dir, summary.key_dir / KEY_FILE, PASSWORD)
    assert (restored.output_dir / "letters" / "letter.txt").read_text(encoding="utf-8") == GERMAN_LETTER
    assert restored.counts["TERM"] == 3 and not restored.unknown_tokens

    # Run again without the word: it is no longer replaced, although the key still knows it.
    second = anonymize_folder(german, PASSWORD, output_dir=tmp_path / "second")
    assert "LUMINA-Studie" in (second.output_dir / "letters" / "letter.txt").read_text(encoding="utf-8")


def test_an_added_word_in_english_and_at_a_level_without_a_key(english, tmp_path):
    review = Review(extra=["Halcyon"])
    assert by_value(scan_folder(english, review=review).findings, "Halcyon").count == 2
    summary = anonymize_folder(english, PASSWORD, review=review)
    letter = (summary.output_dir / "letters" / "letter.txt").read_text(encoding="utf-8")
    assert "the TERM_0001_V1 trial" in letter and "The TERM_0001 nurse" in letter
    restored = restore_folder(summary.output_dir, summary.key_dir / KEY_FILE, PASSWORD)
    assert (restored.output_dir / "letters" / "letter.txt").read_text(encoding="utf-8") == ENGLISH_LETTER

    rows = clinic_table()
    for row in rows[1:]:
        row[3] = "Halcyon Ward"
    folder = tmp_path / "Tables"
    folder.mkdir()
    write_xlsx(folder / "a.xlsx", rows)
    reduced = anonymize_folder(folder, level=4, review=review)
    out = all_text(reduced.output_dir)
    assert "Halcyon" not in out and "TERM_" in out and "TERM_0001" not in out, "a random code, as no key is kept"
    assert not (reduced.key_dir / KEY_FILE).exists()


# --------------------------------------------------------------------------- single files
def test_only_the_chosen_file_is_read_and_written(german, tmp_path):
    (german / "photo.png").write_bytes(b"not a picture")
    chosen = german / "letters" / "letter.txt"
    scan = scan_folder(german, only=[chosen])
    assert {file for f in scan.findings for file in f.files} == {"letters/letter.txt"}
    assert scan.tables == [] and scan.other_files == ["letters/letter.txt"] and scan.unsupported == []
    assert by_value(scan.findings, "Anna Berger").source == "rule", "the table was not read, so it proves nothing"
    assert read_tables(german, None, [chosen]) == ([], ["letters/letter.txt"])

    # Next to the file, as the app does it for a single file.
    out, key_dir = german / "letter_pseudonymised", german / "letter_privatier"
    summary = anonymize_folder(german, PASSWORD, output_dir=out, key_dir=key_dir, only=[chosen])
    assert summary.processed == ["letters/letter.txt"] and summary.skipped == [] and summary.key_dir == key_dir
    assert [str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()] == ["letters/letter.txt"]
    assert (key_dir / KEY_FILE).exists() and summary.check.tables == []
    written = (out / "letters" / "letter.txt").read_text(encoding="utf-8")
    assert "Berger" not in written and "PERSON_0001" in written

    with pytest.raises(ValueError):
        anonymize_folder(german, PASSWORD, output_dir=german / "x", key_dir=key_dir, only=[tmp_path / "elsewhere.txt"])
    with pytest.raises(ValueError):  # without `only` the copy still has to be outside
        anonymize_folder(german, PASSWORD, output_dir=german / "x")

    (out / "notes.txt").write_text("PERSON_0001 again", encoding="utf-8")
    restored = restore_folder(out, key_dir / KEY_FILE, PASSWORD, only=[Path("letters/letter.txt")])
    assert restored.processed == ["letters/letter.txt"]
    assert [p.name for p in restored.output_dir.rglob("*") if p.is_file()] == ["letter.txt"]
    assert (restored.output_dir / "letters" / "letter.txt").read_text(encoding="utf-8") == GERMAN_LETTER
