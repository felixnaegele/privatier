"""One person gets one code, two people never share one, and no information is lost."""

import datetime as dt
import re
import shutil

import pandas as pd
import pyreadstat
import pytest
from openpyxl import Workbook, load_workbook

from privatier.engine import KEY_FILE, anonymize_folder, restore_folder
from privatier.identity import BirthDate, name_key, parse_birth_date
from privatier.pseudonyms import TOKEN_RE, Pseudonymizer
from privatier.vault import load_vault

PASSWORD = "correct horse battery"


def run(tmp_path, files: dict[str, str], **kwargs):
    src = tmp_path / "Studie"
    src.mkdir(exist_ok=True)
    for name, content in files.items():
        (src / name).write_text(content, encoding="utf-8")
    summary = anonymize_folder(src, PASSWORD, **kwargs)
    return tmp_path / "Studie_anonymized", summary


def table(out, name):
    lines = (out / name).read_text(encoding="utf-8-sig").splitlines()
    return [line.split(";") for line in lines]


def people_of(tmp_path):
    return load_vault(tmp_path / "Studie_privatier" / KEY_FILE, PASSWORD)["people"]


# --- same name, different people ------------------------------------------------
def test_same_name_different_birth_date_are_different_people(tmp_path):
    out, summary = run(
        tmp_path, {"a.csv": "Vorname;Nachname;Geburtsdatum\nMax;Müller;12.05.1975\nMax;Müller;03.11.1962\n"}
    )
    rows = table(out, "a.csv")
    assert rows[1][0] != rows[2][0] and rows[1][1] != rows[2][1]
    assert summary.warnings == []  # the birth dates settled it: nothing to ask
    assert "identity_settled" in (tmp_path / "Studie_privatier" / "audit.jsonl").read_text(encoding="utf-8")


def test_same_name_same_birth_year_only_the_full_date_tells_them_apart(tmp_path):
    out, _ = run(tmp_path, {"a.csv": "Vorname;Nachname;Geburtsdatum\nLisa;Braun;01.03.1980\nLisa;Braun;09.10.1980\n"})
    rows = table(out, "a.csv")
    assert rows[1][2] == rows[2][2] == "1980"  # the year alone would not separate them...
    assert rows[1][0] != rows[2][0]  # ...their codes do


def test_same_name_different_patient_id_are_different_people(tmp_path):
    out, _ = run(tmp_path, {"a.csv": "Patienten-ID;Name\nA1;Max Müller\nA2;Max Müller\n"})
    rows = table(out, "a.csv")
    assert rows[1][1] != rows[2][1]


def test_same_name_and_birth_date_but_different_patient_id_is_flagged_not_merged(tmp_path):
    out, summary = run(
        tmp_path, {"a.csv": "Patienten-ID;Name;Geburtsdatum\nA1;Max Müller;12.05.1975\nA2;Max Müller;12.05.1975\n"}
    )
    rows = table(out, "a.csv")
    assert rows[1][1] != rows[2][1]
    assert any("same name and birth date" in note for _, note in summary.warnings)


def test_name_without_evidence_is_not_guessed_when_two_people_fit(tmp_path):
    out, summary = run(
        tmp_path,
        {
            "a.csv": "Name;Geburtsdatum\nMax Müller;12.05.1975\nMax Müller;03.11.1962\n",
            "b.csv": "Name;Score\nMax Müller;5\n",
        },
    )
    known = {table(out, "a.csv")[1][0], table(out, "a.csv")[2][0]}
    assert table(out, "b.csv")[1][0] not in known
    assert any("not enough information" in note for _, note in summary.warnings)


# --- same person, one code ------------------------------------------------------
def test_one_person_keeps_one_code_across_files_and_forms(tmp_path):
    out, _ = run(
        tmp_path,
        {
            "a.csv": "Vorname;Nachname;Geburtsdatum\nEva;Klein;01.02.1990\n",
            "b.csv": "Name;Geburtsdatum\nEva Klein;1990-02-01\n",
            "c.csv": "Name;Geburtsdatum\n\"Klein, Eva\";01.02.1990\n",
        },
    )
    first, last = table(out, "a.csv")[1][:2]
    full = table(out, "b.csv")[1][0]
    assert first == f"{full}_F" and last == f"{full}_L"
    assert table(out, "c.csv")[1][0].startswith(full)


def test_spelling_variants_are_one_person(tmp_path):
    out, _ = run(tmp_path, {"a.csv": "Name;Geburtsdatum\nJörg Weiß;05.05.1955\nJoerg Weiss;05.05.1955\n"})
    rows = table(out, "a.csv")
    assert rows[1][0] == "PERSON_0001" and rows[2][0].startswith("PERSON_0001_")


def test_several_cases_of_one_patient_stay_one_person(tmp_path):
    out, _ = run(
        tmp_path,
        {"a.csv": "Fallnummer;Name;Geburtsdatum\nF1;Max Müller;12.05.1975\nF2;Max Müller;12.05.1975\n"},
    )
    rows = table(out, "a.csv")
    assert rows[1][1] == rows[2][1] and rows[1][0] != rows[2][0]


def test_id_links_a_row_without_birth_date(tmp_path):
    out, _ = run(
        tmp_path,
        {
            "a.csv": "Patienten-ID;Name;Geburtsdatum\nA1;Max Müller;12.05.1975\nA2;Max Müller;03.11.1962\n",
            "b.csv": "Patienten-ID;Name;Score\nA2;Max Müller;9\n",
        },
    )
    assert table(out, "b.csv")[1][1] == table(out, "a.csv")[2][1]


def test_same_id_with_different_names_are_different_people(tmp_path):
    out, _ = run(tmp_path, {"a.csv": "ID;Name\n1;Tom Berg\n", "b.csv": "ID;Name\n1;Ina Tal\n"})
    assert table(out, "a.csv")[1][1] != table(out, "b.csv")[1][1]


# --- names in free text ---------------------------------------------------------
TWO_MAX = "Name;Geburtsdatum\nMax Müller;12.05.1975\nMax Müller;03.11.1962\n"


def test_letter_is_linked_by_the_birth_date_next_to_the_name(tmp_path):
    out, _ = run(tmp_path, {"a.csv": TWO_MAX, "b.txt": "Patient Max Müller, geb. 03.11.1962, kam zur Kontrolle.\n"})
    code = table(out, "a.csv")[2][0]
    assert (out / "b.txt").read_text(encoding="utf-8").startswith(f"Patient {code},")


def test_birth_date_elsewhere_in_the_letter_decides_too(tmp_path):
    out, _ = run(
        tmp_path, {"a.csv": TWO_MAX, "b.txt": "Betreff: Herr Max Müller\nGeburtsdatum: 03.11.1962\nAlles gut.\n"}
    )
    assert table(out, "a.csv")[2][0] in (out / "b.txt").read_text(encoding="utf-8")


def test_ambiguous_mention_is_kept_apart_and_flagged(tmp_path):
    out, summary = run(tmp_path, {"a.csv": TWO_MAX, "b.txt": "Rückfrage zu Herrn Max Müller.\n"})
    note = (out / "b.txt").read_text(encoding="utf-8")
    assert "Müller" not in note
    assert table(out, "a.csv")[1][0] not in note and table(out, "a.csv")[2][0] not in note
    assert any(file == "b.txt" and "different people" in n for file, n in summary.warnings)


def test_surname_alone_is_kept_apart_and_flagged_not_assumed(tmp_path):
    out, summary = run(tmp_path, {"a.txt": "Patientin Anna Schmidt, geb. 12.05.1975. Frau Schmidt war zufrieden.\n"})
    text = (out / "a.txt").read_text(encoding="utf-8")
    assert "Patientin PERSON_0001," in text and "Frau PERSON_0001" not in text and "Schmidt" not in text
    assert any("may belong to PERSON_0001" in note for _, note in summary.warnings)


def test_surname_links_when_the_user_says_so(tmp_path):
    out, _ = run(
        tmp_path, {"a.txt": "Patientin Anna Schmidt, geb. 12.05.1975. Frau Schmidt war zufrieden.\n"}, link_by_name=True
    )
    assert "Frau PERSON_0001_L " in (out / "a.txt").read_text(encoding="utf-8")


def test_surname_is_not_linked_when_two_people_in_the_document_fit(tmp_path):
    out, _ = run(
        tmp_path,
        {"a.txt": "Patient Max Müller, geb. 12.05.1975. Patient Eva Müller, geb. 03.11.1962. Herr Müller rief an.\n"},
    )
    text = (out / "a.txt").read_text(encoding="utf-8")
    last_sentence = text.split(". ")[-1]
    assert "Müller" not in text
    assert "PERSON_0001" not in last_sentence and "PERSON_0002" not in last_sentence


def test_surname_is_not_linked_to_someone_of_another_gender(tmp_path):
    out, _ = run(
        tmp_path,
        {"a.csv": "Name;Geburtsdatum;Geschlecht\nAnna Schmidt;12.05.1975;w\n", "a.txt": "x"}
        | {"b.txt": "Frau Anna Schmidt, geb. 12.05.1975. Ihr Mann, Herr Schmidt, rief an.\n"},
    )
    text = (out / "b.txt").read_text(encoding="utf-8")
    assert "Frau PERSON_0001," in text and "Herr PERSON_0001" not in text and "Schmidt" not in text


def test_doctor_with_the_same_name_as_a_patient_is_kept_apart(tmp_path):
    out, summary = run(
        tmp_path,
        {
            "a.csv": "Name;Geburtsdatum\nJürgen Weiß;21.01.1958\n",
            "b.txt": "Rückfragen gerne an Herrn Dr. Jürgen Weiß.\n",
        },
    )
    assert table(out, "a.csv")[1][0] not in (out / "b.txt").read_text(encoding="utf-8")
    assert any(file == "b.txt" for file, _ in summary.warnings)


def test_doctor_title_inside_the_ai_finding_is_kept_apart(tmp_path):
    """The real AI returns the whole of "Herrn Dr. Jürgen Weiß" as the name."""
    from privatier.detect import PatternDetector
    from privatier.detect.base import Span

    class TitleAI:
        name = "ner"

        def detect(self, text):
            needle = "Herrn Dr. Jürgen Weiß"
            at = text.find(needle)
            return [] if at < 0 else [Span(at, at + len(needle), "PERSON", needle, "ner", 0.9)]

    out, _ = run(
        tmp_path,
        {"a.csv": "Name;Geburtsdatum\nJürgen Weiß;21.01.1958\n", "b.txt": "Rückfragen gerne an Herrn Dr. Jürgen Weiß.\n"},
        detectors=[PatternDetector(), TitleAI()],
    )
    text = (out / "b.txt").read_text(encoding="utf-8")
    assert table(out, "a.csv")[1][0] not in text and "Weiß" not in text


def test_same_id_on_different_people_is_flagged(tmp_path):
    _, summary = run(tmp_path, {"a.csv": "ID;Name\n1;Tom Berg\n", "b.csv": "ID;Name\n1;Ina Tal\n"})
    assert any("same ID number" in note for _, note in summary.warnings)


def test_doctor_column_is_not_the_patient(tmp_path):
    out, _ = run(tmp_path, {"a.csv": "Name;Geburtsdatum;Hausarzt\nMax Müller;12.05.1975;Max Müller\n"})
    row = table(out, "a.csv")[1]
    assert row[0] != row[2] and "Müller" not in row[2]


# --- nothing is lost ------------------------------------------------------------
def round_trip(tmp_path, out):
    results = tmp_path / "Ergebnisse"
    shutil.copytree(out, results)
    restore_folder(results, tmp_path / "Studie_privatier" / KEY_FILE, PASSWORD)
    return tmp_path / "Ergebnisse_restored"


def test_csv_round_trip_is_exact(tmp_path):
    original = (
        "Patienten-ID;Vorname;Nachname;Name;Geburtsdatum;Gruppe\n"
        "A1;Max;Müller;WEIß, JÖRG;12.05.1975;Intervention\n"
        "A2;Max;Müller;Jörg Weiß;03/11/1962;Kontrolle\n"
    )
    out, _ = run(tmp_path, {"a.csv": original})
    assert "12.05.1975" not in (out / "a.csv").read_text(encoding="utf-8")
    restored = (round_trip(tmp_path, out) / "a.csv").read_text(encoding="utf-8-sig")
    assert restored == original


def test_file_names_are_kept_and_tokens_in_result_names_are_restored(tmp_path):
    src = tmp_path / "Studie"
    src.mkdir()
    (src / "Akte_Anna_Schmidt_12031948.txt").write_text("Patientin Anna Schmidt", encoding="utf-8")
    anonymize_folder(src, PASSWORD)
    out = tmp_path / "Studie_anonymized"
    assert [p.name for p in out.iterdir()] == ["Akte_Anna_Schmidt_12031948.txt"]
    results = tmp_path / "Ergebnisse"
    results.mkdir()
    (results / "Bericht_PERSON_0001.txt").write_text("PERSON_0001", encoding="utf-8")
    restore_folder(results, tmp_path / "Studie_privatier" / KEY_FILE, PASSWORD)
    assert (tmp_path / "Ergebnisse_restored" / "Bericht_Anna Schmidt.txt").exists()


def test_full_birth_dates_are_kept_in_the_key_only(tmp_path):
    out, _ = run(tmp_path, {"a.csv": "Name;Geburtsdatum\nMax Müller;12.05.1975\n"})
    assert "12.05.1975" not in (out / "a.csv").read_text(encoding="utf-8")
    assert people_of(tmp_path)[0]["births"][0]["raw"] == "12.05.1975"
    assert "12.05.1975" not in (tmp_path / "Studie_privatier" / "audit.jsonl").read_text(encoding="utf-8")
    assert b"12.05.1975" not in (tmp_path / "Studie_privatier" / KEY_FILE).read_bytes()


def test_codes_stay_the_same_when_run_again(tmp_path):
    out, _ = run(tmp_path, {"a.csv": TWO_MAX})
    before = table(out, "a.csv")
    (tmp_path / "Studie" / "b.csv").write_text("Name;Geburtsdatum\nMax Müller;03.11.1962\n", encoding="utf-8")
    second = tmp_path / "second"
    anonymize_folder(tmp_path / "Studie", PASSWORD, output_dir=second, work_dir=tmp_path / "Studie_privatier")
    assert table(second, "a.csv") == before
    assert table(second, "b.csv")[1][0] == before[2][0]


def test_review_notes_never_contain_real_values(tmp_path):
    _, summary = run(
        tmp_path,
        {
            "a.csv": TWO_MAX,
            "b.txt": "Rückfrage zu Herrn Max Müller.\n",
            "c.csv": "Patienten-ID;Name;Geburtsdatum\nA1;Eva Klein;01.02.1990\nA2;Eva Klein;01.02.1990\n",
        },
    )
    assert summary.warnings
    joined = " ".join(note for _, note in summary.warnings)
    audit = (tmp_path / "Studie_privatier" / "audit.jsonl").read_text(encoding="utf-8")
    for value in ("Müller", "Max", "Klein", "Eva", "1975", "A1"):
        assert value not in joined
        if value != "Max":
            assert value not in audit


# --- SPSS: nothing dropped -------------------------------------------------------
def test_spss_keeps_user_missing_codes_labels_and_notes(tmp_path):
    src = tmp_path / "Studie"
    src.mkdir()
    df = pd.DataFrame(
        {
            "name": ["Max Müller", "Eva Klein"],
            "gebdat": pd.to_datetime(["1975-05-12", "1990-02-01"]),
            "visite": pd.to_datetime(["2023-01-02", "2023-03-04"]),
            "score": [12.5, 99.0],
            "kommentar": ["ok", "Patient Eva Klein unsicher"],
        }
    )
    pyreadstat.write_sav(
        df,
        str(src / "a.sav"),
        file_label="Studie von Patient Eva Klein",
        note="Erfasst bei Patient Eva Klein",
        missing_ranges={"score": [99.0]},
        variable_value_labels={"score": {99.0: "verweigert"}},
        variable_format={"score": "F8.2"},
    )
    anonymize_folder(src, PASSWORD)
    out, meta = pyreadstat.read_sav(str(tmp_path / "Studie_anonymized" / "a.sav"), user_missing=True)
    assert list(out["score"]) == [12.5, 99.0]
    assert meta.missing_ranges["score"] == [{"lo": 99.0, "hi": 99.0}]
    assert meta.variable_value_labels["score"] == {99.0: "verweigert"}
    assert meta.original_variable_types["score"] == "F8.2"
    assert "Klein" not in meta.file_label and "PERSON_" in meta.file_label
    assert "Klein" not in " ".join(meta.notes) and "Klein" not in " ".join(out["kommentar"])
    assert list(out["gebdat"]) == [1975, 1990]
    assert out["visite"].iloc[0] == pd.Timestamp("2023-01-02")  # kept, with a warning (see README)
    assert out["name"].iloc[1] == "PERSON_0002" or out["name"].iloc[1].startswith("PERSON_")


# --- places where names used to survive ------------------------------------------
def test_csv_with_title_rows_above_the_header(tmp_path):
    out, _ = run(tmp_path, {"a.csv": "Export 2024;;\n;;\nVorname;Nachname;Telefon\nRainer;Zufall;0151 111222\n"})
    text = (out / "a.csv").read_text(encoding="utf-8")
    assert "Rainer" not in text and "Zufall" not in text and "Export 2024" in text and "Vorname;Nachname" in text


def test_excel_formulas_page_headers_and_properties(tmp_path):
    src = tmp_path / "Studie"
    src.mkdir()
    wb = Workbook()
    ws = wb.active
    ws.append(["Vorname", "Nachname", "Geburtsdatum", "Punkte", "Formel"])
    ws.append(["Ute", "Sommer", dt.datetime(1970, 1, 2), 3, '=CONCATENATE("Ute"," Sommer")'])
    ws.append([None, None, None, 4, "=D2+D3"])
    ws.oddHeader.center.text = "Kopfzeile Ute Sommer"
    wb.properties.title = "Akte Ute Sommer"
    wb.save(src / "a.xlsx")
    anonymize_folder(src, PASSWORD)
    result = load_workbook(tmp_path / "Studie_anonymized" / "a.xlsx")
    sheet = result.active
    assert sheet["A2"].value == "PERSON_0001_F" and sheet["B2"].value == "PERSON_0001_L"
    assert sheet["E3"].value == "=D2+D3"
    assert "Sommer" not in sheet["E2"].value and sheet["E2"].value.startswith("=CONCATENATE(")
    assert "Sommer" not in sheet.oddHeader.center.text
    assert "Sommer" not in result.properties.title


# --- building blocks -------------------------------------------------------------
@pytest.mark.parametrize(
    "a, b, same",
    [
        ("12.05.1975", "1975-05-12", True),
        (dt.datetime(1975, 5, 12), "12.05.1975", True),
        ("12.05.75", "12.05.1975", True),
        ("05/12/1975", "12.05.1975", True),  # month first or day first: both are possible
        ("13/05/1975", "1975-05-13", True),
        ("12.05.1975", "13.05.1975", False),
        ("1975", "12.05.1975", True),
        ("1975", "1976", False),
        ("1975", "03.11.1962", False),
    ],
)
def test_birth_dates_compare_across_formats(a, b, same):
    assert parse_birth_date(a).same_person_possible(parse_birth_date(b)) is same


@pytest.mark.parametrize("value", [None, "", "  ", float("nan"), "unbekannt", "99.99.1975"])
def test_unusable_birth_dates(value):
    assert parse_birth_date(value) is None


def test_birth_date_survives_the_key_file():
    original = parse_birth_date("12.05.1975")
    assert BirthDate.from_dict(original.to_dict()) == original


@pytest.mark.parametrize(
    "a, b",
    [("Max Müller", "Müller, Max"), ("Max Müller", "MAX MUELLER"), ("Jörg Weiß", "Joerg Weiss"), ("Dr. Eva Kern", "Eva Kern")],
)
def test_name_forms_compare_equal(a, b):
    assert name_key(a) == name_key(b)


@pytest.mark.parametrize(
    "token, base, suffix",
    [("PERSON_0001", "0001", None), ("PERSON_0001_F", "0001", "F"), ("person 0012_v2", "0012", "v2")],
)
def test_token_forms(token, base, suffix):
    m = TOKEN_RE.fullmatch(token)
    assert m.group(2) == base and m.group(3) == suffix


def test_token_inside_a_file_name():
    assert TOKEN_RE.search("Arztbrief_PERSON_0021").group(2) == "0021"


def test_form_codes_survive_the_key_file():
    p = Pseudonymizer()
    base = p.new_person("Max Müller")
    first = p.form_of(base, "Max", "F")
    again = Pseudonymizer.from_dict(p.to_dict())
    assert first == f"{base}_F" and again.original(first) == "Max"
    assert again.form_of(base, "Max", "F") == first
    assert again.new_person("Eva Klein") == "PERSON_0002"


# --- found by testing on hard German data (tools/hard_data.py) ---------------------
def test_mother_in_the_letter_does_not_take_over_the_patients_surname(tmp_path):
    """The real mix-up: "Frau Berger" got the mother's code, as she was the only Berger recognised."""
    files = {
        "a.csv": "Name;Geburtsdatum\nHannah Berger;24.06.1990\n",
        "b.txt": "Betreff Hannah Berger, geb. 24.06.1990. Frau Berger kam mit ihrer Mutter Ingeborg Berger.\n",
    }
    out, _ = run(tmp_path, files)
    text = (out / "b.txt").read_text(encoding="utf-8")
    hannah = table(out, "a.csv")[1][0]
    mother = re.search(r"Mutter (PERSON_\d+)", text).group(1)
    assert mother != hannah
    assert not re.search(rf"Frau {mother}", text)

    other = tmp_path / "with_answer"
    other.mkdir()
    out, _ = run(other, files, link_by_name=True)
    assert f"Frau {table(out, 'a.csv')[1][0]}_L" in (out / "b.txt").read_text(encoding="utf-8")


def test_birth_date_written_with_a_month_name_counts(tmp_path):
    out, _ = run(
        tmp_path,
        {
            "a.csv": "Name;Geburtstag\nJürgen Schäfer;7. März 1949\nJürgen Schäfer;19. Juli 1971\n",
            "b.csv": "Name;Geburtsdatum\nSchaefer, Juergen;07.03.1949\nSchaefer, Juergen;19.07.1971\n",
        },
    )
    a, b = table(out, "a.csv"), table(out, "b.csv")
    assert a[1][1] == "1949" and a[1][0] != a[2][0]
    assert a[1][0].split("_V")[0] == b[1][0].split("_V")[0]
    assert a[2][0].split("_V")[0] == b[2][0].split("_V")[0]


@pytest.mark.parametrize("value, iso", [("7. März 1949", "1949-03-07"), ("March 7, 1949", "1949-03-07"), ("7 Dez. 2001", "2001-12-07")])
def test_month_names(value, iso):
    assert parse_birth_date(value).dates == {iso}


def test_word_form_keeps_its_labels_and_links_the_person(tmp_path):
    from docx import Document

    src = tmp_path / "Studie"
    src.mkdir()
    doc = Document()
    table_ = doc.add_table(rows=3, cols=2)
    for r, (label, value) in enumerate([("Name, Vorname", "Sommer, Greta"), ("Geburtsdatum", "30.09.1958"), ("Teilnehmer-Nr.", "T-4471")]):
        table_.cell(r, 0).text = label
        table_.cell(r, 1).text = value
    doc.add_paragraph("Ich, Greta Sommer, stimme zu. Im Sommer 2023 fand die Erhebung statt.")
    doc.save(src / "a.docx")
    anonymize_folder(src, PASSWORD)
    result = Document(tmp_path / "Studie_anonymized" / "a.docx")
    cells = [[c.text for c in row.cells] for row in result.tables[0].rows]
    assert [row[0] for row in cells] == ["Name, Vorname", "Geburtsdatum", "Teilnehmer-Nr."]
    assert "Sommer" not in cells[0][1] and "1958" not in cells[1][1] and "4471" not in cells[2][1]
    sentence = result.paragraphs[0].text
    assert "Im Sommer 2023" in sentence and "Greta" not in sentence
    assert re.search(r"PERSON_\d+", sentence).group(0) == re.search(r"PERSON_\d+", cells[0][1]).group(0)


class WrongAI:
    """Finds the name, but also words that are not names, the way the real model does."""

    name = "ner"
    GUESSES = {"Thomas": "PERSON", "Pat.": "PERSON", "Vater": "PERSON", "RS": "ORG", "Lange": "PERSON",
               "Morbus Alzheimer": "ORG", "Gruppe A": "ORG", "Werk": "ORG", "Verlauf_Berger": "PERSON"}

    def detect(self, text):
        from privatier.detect.base import Span

        return [
            Span(m.start(), m.end(), etype, word, "ner", 0.9)
            for word, etype in self.GUESSES.items()
            for m in re.finditer(rf"(?<!\w){re.escape(word)}(?!\w)", text)
        ]


def test_a_single_ai_guess_does_not_spread(tmp_path):
    from privatier.detect import PatternDetector

    out, _ = run(
        tmp_path,
        {
            "a.csv": "Pat.-Nr.;Bemerkung;Werk\n1;RS mit Pat. wegen Morbus Alzheimer;x\n",
            "b.txt": "Vater ist da. Lange Zeit gut. Gruppe A. Das Werk von Thomas.\n",
        },
        detectors=[PatternDetector(), WrongAI()],
    )
    rows = table(out, "a.csv")
    assert rows[0] == ["Pat.-Nr.", "Bemerkung", "Werk"]
    assert rows[1][1] == "RS mit Pat. wegen Morbus Alzheimer"
    text = (out / "b.txt").read_text(encoding="utf-8")
    assert text.startswith("Vater ist da. Lange Zeit gut. Gruppe A.") and "Thomas" not in text


def test_note_in_a_table_row_is_flagged_and_links_only_when_told(tmp_path):
    files = {"a.csv": "Name;Geburtsdatum;Bemerkung\nMax Schäfer;01.01.1950;Herr Schäfer kam\nEva Schäfer;02.02.1960;Frau Schäfer kam\n"}
    out, summary = run(tmp_path, files)
    rows = table(out, "a.csv")
    assert "Schäfer" not in str(rows) and f"Herr {rows[1][0]}" not in rows[1][2]
    assert any("note may refer to" in note for _, note in summary.warnings)

    other = tmp_path / "with_answer"
    other.mkdir()
    out, _ = run(other, files, link_by_name=True)
    rows = table(out, "a.csv")
    assert rows[1][2].startswith(f"Herr {rows[1][0]}_L") and rows[2][2].startswith(f"Frau {rows[2][0]}_L")


def test_genitive_and_unusual_letters(tmp_path):
    out, _ = run(
        tmp_path,
        {
            "a.csv": "Name;Geburtsdatum\nÖzlem Şahin;01.01.1980\nŁukasz Dąbrowski;02.02.1981\nMax Müller;03.03.1982\n",
            "b.txt": "Frau Şahin kam. Herr Łukasz Dąbrowski kam. Herr Müllers Ehefrau rief an. Frau Mueller auch.\n",
        },
    )
    text = (out / "b.txt").read_text(encoding="utf-8")
    for value in ("Şahin", "Dąbrowski", "Łukasz", "Müller", "Mueller"):
        assert value not in text
    assert "Ehefrau rief an" in text


def test_name_stops_at_a_disease_and_the_disease_stays(tmp_path):
    out, _ = run(tmp_path, {"a.txt": "Frau Klara Öztürks Morbus Crohn ist stabil. Morbus Crohn bleibt.\n"})
    text = (out / "a.txt").read_text(encoding="utf-8")
    assert text.count("Morbus Crohn") == 2 and "Öztürk" not in text and "Klara" not in text


@pytest.mark.parametrize(
    "keep",
    ["10-0-10 IE", "1-0-1", "130/80 mmHg", "Lange Zeit", "im Mai", "Im Sommer 2023", "Berger-Krankheit"],
)
def test_ordinary_text_survives_people_with_such_surnames(tmp_path, keep):
    out, _ = run(
        tmp_path,
        {
            "a.csv": "Name;Geburtsdatum\nJana Mai;01.01.1980\nKarl Lange;02.02.1981\nGreta Sommer;03.03.1982\nHans Berger;04.04.1983\n",
            "b.txt": f"Vor dem Satz. {keep} und danach.\n",
        },
    )
    assert keep in (out / "b.txt").read_text(encoding="utf-8")


def test_coded_spss_column_keeps_its_codes_and_cleans_its_labels(tmp_path):
    src = tmp_path / "Studie"
    src.mkdir()
    df = pd.DataFrame({"behandler": [1.0, 2.0], "vpn": [100.0, 101.0]})
    pyreadstat.write_sav(
        df,
        str(src / "a.sav"),
        column_labels=["Behandelnder Arzt", "Versuchsperson"],
        variable_value_labels={"behandler": {1.0: "Dr. Weiß", 2.0: "Prof. Hahn"}},
    )
    anonymize_folder(src, PASSWORD)
    out, meta = pyreadstat.read_sav(str(tmp_path / "Studie_anonymized" / "a.sav"))
    assert list(out["behandler"]) == [1.0, 2.0]
    assert "Weiß" not in str(meta.variable_value_labels) and "Hahn" not in str(meta.variable_value_labels)
    assert list(out["vpn"])[0].startswith("ID_")  # "Versuchsperson" is a subject ID


def test_folder_names_stay_too(tmp_path):
    src = tmp_path / "Studie"
    (src / "Schulz_Peter_12031948").mkdir(parents=True)
    (src / "Schulz_Peter_12031948" / "a.txt").write_text("Patient: Schulz, Peter (*12.3.1948)\n", encoding="utf-8")
    anonymize_folder(src, PASSWORD)
    result = tmp_path / "Studie_anonymized" / "Schulz_Peter_12031948" / "a.txt"
    assert "Schulz" not in result.read_text(encoding="utf-8")


def test_the_hard_dataset_has_no_problems_with_rules_only(capsys):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "tools" / "hard_data.py"
    spec = importlib.util.spec_from_file_location("hard_data", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.show(module.run(use_ai=False)) == 0, capsys.readouterr().out


def test_birth_year_column_keeps_two_people_apart(tmp_path):
    """The merge found by the third hard test: Geburtsjahr was not understood as birth information."""
    out, _ = run(tmp_path, {"a.csv": "Nachname;Vorname;Geburtsjahr;Score\nHoffmann;Karin;1961;21\nHoffmann;Karin;1984;9\n"})
    rows = table(out, "a.csv")
    assert rows[1][0] != rows[2][0] and rows[1][2] == "1961" and rows[2][2] == "1984"


def test_birth_year_links_to_the_person_with_that_full_birth_date(tmp_path):
    out, summary = run(
        tmp_path,
        {
            "a.csv": "Name;Vorname;geb.\nHoffmann;Karin;23.08.1961\nHoffmann;Karin;14.12.1984\n",
            "b.csv": "Nachname;Vorname;Jahrgang\nHoffmann;Karin;1984\n",
            "c.txt": "Interview mit Karin Hoffmann (Jg. 1961) in der Praxis.\n",
        },
    )
    a = table(out, "a.csv")
    assert table(out, "b.csv")[1][0] == a[2][0]
    base = re.match(r"PERSON_\d+", a[1][0]).group(0)
    assert base in (out / "c.txt").read_text(encoding="utf-8")


def test_name_column_next_to_first_name_is_the_surname(tmp_path):
    out, _ = run(
        tmp_path,
        {
            "a.csv": "Name;Vorname;Geburtsdatum\nHoffmann;Karin;23.08.1961\n",
            "b.csv": "Patient;Geburtsdatum\nKarin Hoffmann;23.08.1961\n",
        },
    )
    row = table(out, "a.csv")[1]
    full = table(out, "b.csv")[1][0]
    assert row[0] == f"{full}_L" and row[1] == f"{full}_F"


def test_study_code_is_evidence_and_separates_people(tmp_path):
    out, _ = run(tmp_path, {"a.csv": "Code;Nachname;Vorname\nK01;Hoffmann;Karin\nK02;Hoffmann;Karin\n"})
    rows = table(out, "a.csv")
    assert rows[1][1] != rows[2][1]


def test_words_in_file_names_are_not_read_as_names(tmp_path):
    from privatier.detect import PatternDetector

    src = tmp_path / "Studie"
    src.mkdir()
    (src / "Gutachten_Verlauf.txt").write_text("Das Gutachten und der Verlauf.\n", encoding="utf-8")
    anonymize_folder(src, PASSWORD, detectors=[PatternDetector(), WrongAI()])
    only = next((tmp_path / "Studie_anonymized").iterdir())
    assert only.name == "Gutachten_Verlauf.txt" and only.read_text(encoding="utf-8") == "Das Gutachten und der Verlauf.\n"


def test_ai_finding_stops_at_the_end_of_the_line(tmp_path):
    from privatier.detect import PatternDetector
    from privatier.detect.base import Span

    class TwoLineAI:
        name = "ner"

        def detect(self, text):
            needle = "Leyla Haddad\nKlient"
            at = text.find(needle)
            return [] if at < 0 else [Span(at, at + len(needle), "PERSON", needle, "ner", 0.9)]

    out, _ = run(tmp_path, {"a.txt": "Dabei: Leyla Haddad\nKlient lebt in Deutschland.\n"}, detectors=[PatternDetector(), TwoLineAI()])
    text = (out / "a.txt").read_text(encoding="utf-8")
    assert "\nKlient lebt" in text and "Haddad" not in text


def test_particles_and_professional_titles(tmp_path):
    out, _ = run(
        tmp_path,
        {"a.txt": "Herr Willem van den Berg kam. Frau Dipl.-Psych. Marta Nowak untersuchte. Personalausweis L01X00T47.\nIn der Holstenstraße wohnt sie.\n"},
    )
    text = (out / "a.txt").read_text(encoding="utf-8")
    for value in ("Willem", "van den Berg", "Marta", "Nowak", "L01X00T47", "Holstenstraße"):
        assert value not in text
    assert "wohnt sie" in text


def test_surname_of_several_words_is_flagged_within_the_document(tmp_path):
    text = "Gutachten über Herrn Willem van den Berg, geb. 30.04.1955. Herr van den Berg war kooperativ.\n"
    out, summary = run(tmp_path, {"a.txt": text})
    result = (out / "a.txt").read_text(encoding="utf-8")
    assert "Herrn PERSON_0001," in result and "Herr PERSON_0001" not in result and "Berg" not in result
    assert any("may belong to PERSON_0001" in note for _, note in summary.warnings)


def test_table_with_a_name_in_its_file_name_keeps_it(tmp_path):
    out, summary = run(tmp_path, {"Mueller_Max_1962.csv": "Name;DOB\nMax Mueller;03.11.1962\n"})
    assert (out / "Mueller_Max_1962.csv").exists()
    assert any("Names are kept on purpose" in note for note in summary.notes)


# --- tables first: what real study files showed -----------------------------------
def excel(tmp_path, rows, name="a.xlsx"):
    src = tmp_path / "Studie"
    src.mkdir(exist_ok=True)
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    wb.save(src / name)
    return src


def output_rows(tmp_path, name="a.xlsx"):
    return [list(r) for r in load_workbook(tmp_path / "Studie_anonymized" / name).active.iter_rows(values_only=True)]


@pytest.mark.parametrize(
    "header",
    ["code_sex", "Mitralvalve_repair_code", "ENDOCARDITIS_CODE", "PoorMobility", "Mobility", "Mitralstenosis", "group",
     "visit_type", "SEX1=Male,2=Female", "Hypertension", "PreoperativeCTscan", "Above_75"],
)
def test_clinical_columns_are_not_mistaken_for_identifiers(header):
    from privatier.tables import classify_header

    assert classify_header(header) is None


@pytest.mark.parametrize(
    "header, category",
    [("Forename", "PERSON"), ("Family name", "PERSON"), ("Surname", "PERSON"), ("Given name", "PERSON"),
     ("Patient Name", "PERSON"), ("Last_Name", "PERSON"), ("LastName", "PERSON"), ("GP", "PERSON"), ("Surgeon", "PERSON"),
     ("Consultant", "PERSON"), ("Investigator", "PERSON"), ("Next of kin", "PERSON"), ("D.O.B.", "DOB"), ("DOB", "DOB"),
     ("Dateofbirth", "DOB"), ("Date of Birth", "DOB"), ("Birthdate", "DOB"), ("Year of birth", "BIRTH_YEAR"),
     ("NHS number", "ID"), ("MRN", "ID"), ("SSN", "ID"), ("HospitalID", "ID"), ("Hospital Number", "ID"),
     ("StudyID", "ID"), ("ParticipantID", "ID"), ("Record ID", "ID"), ("Subject Code", "ID"), ("CenterPat_ID", "ID"),
     ("Postcode", "ADDRESS"), ("ZIP", "ADDRESS"), ("Town", "ADDRESS"), ("City", "ADDRESS"), ("Street Address", "ADDRESS"),
     ("Telephone", "PHONE"), ("Mobile", "PHONE"), ("Email", "EMAIL")],
)
def test_english_headers(header, category):
    from privatier.tables import classify_header

    assert classify_header(header) == category


def test_every_clinical_value_stays_exactly_as_it_was(tmp_path):
    rows = [
        ["id", "Last_Name", "Name", "Dateofbirth", "AGE", "Weight", "LVEF", "Group", "Status"],
        ["(n)", "(text)", "(text)", "(dd/mm/yyyy)", "(y)", "(kg)", "(%)", "(0=no,1=yes)", "(1=a,2=b)"],
        [1, "Long", "Mark", dt.datetime(1950, 1, 2), 70, "79,5", 55.5, "Intervention", "alive"],
        [2, "White", "Grace", dt.datetime(1960, 3, 4), 60, 80, 40, "Control", "lost to follow up"],
    ]
    anonymize_folder(excel(tmp_path, rows), PASSWORD)
    result = output_rows(tmp_path)
    assert result[1] == rows[1]  # the legend row explains the columns, it is not data
    for before, after in zip(rows[2:], result[2:]):
        assert after[4:] == before[4:]
        assert str(before[1]) not in str(after) and str(before[2]) not in str(after)


def test_dates_as_text_are_kept_like_real_dates_in_the_same_column(tmp_path):
    rows = [["Patient ID", "Date of surgery", "Dateofredo", "Note"]]
    rows += [[f"P{i}", dt.datetime(2020, 1, i + 1), f"{i + 1}.3.2021", "Mr Long called on 3.4.2021"] for i in range(6)]
    _, = anonymize_folder(excel(tmp_path, rows), PASSWORD), 
    result = output_rows(tmp_path)
    assert result[1][1] == dt.datetime(2020, 1, 1) and result[1][2] == "1.3.2021"
    assert "3.4.2021" not in result[1][3] and "Long" not in result[1][3]


def test_date_column_is_found_by_its_values_when_the_header_says_nothing(tmp_path):
    rows = [["Patient ID", "re-hospital"]] + [[f"P{i}", f"{i + 1}.3.2021 Reflux"] for i in range(6)]
    anonymize_folder(excel(tmp_path, rows), PASSWORD)
    assert output_rows(tmp_path)[1][1] == "1.3.2021 Reflux"


def test_column_without_header_holding_names_is_replaced_and_asked_about(tmp_path):
    names = ["Long", "O'Neill", "Müller", "van den Berg", "White", "Nguyen", "Klein"]
    rows = [[None, "numbering"]] + [[n, i] for i, n in enumerate(names)]
    summary = anonymize_folder(excel(tmp_path, rows), PASSWORD)
    result = output_rows(tmp_path)
    assert not any(n in str(result) for n in names)
    assert [r[1] for r in result[1:]] == list(range(7))
    assert any("no header" in note and "names" in note and "column A" in note for _, note in summary.warnings)


def test_column_without_header_holding_dates_could_be_birth_dates(tmp_path):
    rows = [[None, "numbering"]] + [[dt.datetime(1950 + i, 1, 2), i] for i in range(6)]
    summary = anonymize_folder(excel(tmp_path, rows), PASSWORD)
    assert "19" not in str(output_rows(tmp_path)[1][0])
    assert any("no header" in note and "dates" in note for _, note in summary.warnings)


def test_column_without_header_holding_unique_numbers_could_be_an_id(tmp_path):
    rows = [[None, "numbering"]] + [[900000 + i, i] for i in range(6)]
    summary = anonymize_folder(excel(tmp_path, rows), PASSWORD)
    assert str(output_rows(tmp_path)[1][0]).startswith("ID_")
    assert any("no header" in note and "ID" in note for _, note in summary.warnings)


def test_named_column_that_looks_like_names_is_left_and_asked_about(tmp_path):
    names = ["Long", "Smith", "Taylor", "Young", "Brown", "Green"]
    rows = [["Kürzel", "Score"]] + [[n, i] for i, n in enumerate(names)]
    summary = anonymize_folder(excel(tmp_path, rows), PASSWORD)
    assert output_rows(tmp_path)[1][0] == "Long"
    assert any("look like names" in note and "column A" in note for _, note in summary.warnings)


def test_categories_with_few_values_are_not_taken_for_names(tmp_path):
    rows = [["Klappe", "Score"]] + [["St Jude" if i % 2 else "Edwards", i] for i in range(20)]
    summary = anonymize_folder(excel(tmp_path, rows), PASSWORD)
    assert output_rows(tmp_path)[1][0] == "Edwards"
    assert not any("column A" in note for _, note in summary.warnings)


def test_repeated_name_without_evidence_is_not_assumed_to_be_one_person(tmp_path):
    files = {"a.csv": "Name;Score\nFenja Jansen;1\nFenja Jansen;2\n"}
    out, summary = run(tmp_path, files)
    rows = table(out, "a.csv")
    assert rows[1][0] != rows[2][0]
    assert any("may be" in note for _, note in summary.warnings)

    other = tmp_path / "with_answer"
    other.mkdir()
    out, _ = run(other, files, link_by_name=True)
    rows = table(out, "a.csv")
    assert rows[1][0] == rows[2][0]


def test_same_name_across_files_without_evidence_is_asked_about(tmp_path):
    out, summary = run(tmp_path, {"a.csv": "Name;Score\nAna Ruiz;1\n", "b.csv": "Name;Score\nAna Ruiz;2\n"})
    assert table(out, "a.csv")[1][0] != table(out, "b.csv")[1][0]
    assert any("may be" in note for _, note in summary.warnings)


def test_ambiguous_day_month_match_is_flagged(tmp_path):
    out, summary = run(tmp_path, {"a.csv": "Name;DOB\nAna Ruiz;03/04/1975\nAna Ruiz;1975-04-03\n"})
    rows = table(out, "a.csv")
    assert rows[1][0].split("_")[1] == rows[2][0].split("_")[1]
    assert any("two ways" in note for _, note in summary.warnings)


def test_ids_link_people_across_files_without_any_names(tmp_path):
    rows = [["randomisation_id", "BL_EF"]] + [[f"{i}A", 50 + i] for i in range(3)]
    src = excel(tmp_path, rows, "1_baseline.xlsx")
    wb = Workbook()
    for r in [["randomisation_id", "visit_date", "ef"], ["1A", dt.datetime(2022, 1, 1), 44]]:
        wb.active.append(r)
    wb.save(src / "2_mri.xlsx")
    anonymize_folder(src, PASSWORD)
    a, b = output_rows(tmp_path, "1_baseline.xlsx"), output_rows(tmp_path, "2_mri.xlsx")
    assert a[2][0] == b[1][0] and a[2][0].startswith("ID_")


def test_spss_coded_columns_with_code_in_the_name_stay(tmp_path):
    src = tmp_path / "Studie"
    src.mkdir()
    df = pd.DataFrame({"pat_id": [1000.0, 1001.0], "code_sex": [1.0, 2.0], "ENDOCARDITIS_CODE": [0.0, 1.0]})
    pyreadstat.write_sav(df, str(src / "a.sav"))
    anonymize_folder(src, PASSWORD)
    out, _ = pyreadstat.read_sav(str(tmp_path / "Studie_anonymized" / "a.sav"))
    assert list(out["code_sex"]) == [1.0, 2.0] and list(out["ENDOCARDITIS_CODE"]) == [0.0, 1.0]
    assert out["pat_id"].iloc[0].startswith("ID_")


# --- English ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "keep",
    ["White blood cells", "Long term", "May be", "in May", "Young patients", "Black stools", "Parkinson's disease",
     "Crohn's disease", "Kaplan-Meier", "Mann-Whitney", "Carpentier classification", "Alfieri stitch", "Will be seen"],
)
def test_english_words_survive_people_with_such_surnames(tmp_path, keep):
    out, _ = run(
        tmp_path,
        {
            "a.csv": "Name;DOB\nMia White;01/13/1980\nTom Long;01/14/1981\nJana May;01/15/1982\nEve Young;01/16/1983\n"
                     "Kim Black;01/17/1984\nAl Parkinson;01/18/1985\nJo Crohn;01/19/1986\nDan Will;01/20/1987\n"
                     "Lea Carpentier;01/21/1988\nSam Alfieri;01/22/1989\n",
            "b.txt": f"Before this. {keep} and so on.\n",
        },
    )
    assert keep in (out / "b.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "text, gone",
    [
        ("Seen with his wife Mary Jones today.", ["Mary", "Jones"]),
        ("His daughter, Emily, called back.", ["Emily"]),
        ("Dear Dr Thompson, thank you.", ["Thompson"]),
        ("Dear Mrs. O'Brien,", ["O'Brien"]),
        ("Mr Smith's wife called.", ["Smith"]),
        ("John Smith, DOB 03/14/1955, was admitted.", ["John", "Smith", "03/14/1955"]),
        ("Jane Doe (born 1961) attended.", ["Jane", "Doe"]),
        ("Patient: Doe, Jane", ["Doe", "Jane"]),
        ("NHS Number: 943 476 5919", ["943 476 5919"]),
        ("MRN 00123456, SSN 123-45-6789", ["00123456", "123-45-6789"]),
        ("Lives at 42 Oak Street, Boston, MA 02115.", ["Oak Street", "Boston", "02115"]),
        ("Address: 10 High Road, London SW1A 1AA", ["SW1A 1AA"]),
        ("Call 07700 900123 or (617) 555-0199.", ["(617) 555-0199"]),
        ("Consultant Sarah Patel reviewed her.", ["Sarah", "Patel"]),
        ("Sent to j.smith@hospital.example", ["j.smith"]),
    ],
)
def test_english_text(tmp_path, text, gone):
    out, _ = run(tmp_path, {"a.txt": text + "\n"})
    result = (out / "a.txt").read_text(encoding="utf-8")
    assert [g for g in gone if g in result] == []


class EagerAI:
    """Guesses like the real model on table cells without context."""

    name = "ner"
    GUESSES = {"Placebo": "ORG", "T0": "PERSON", "Aortic Stenosis": "PERSON", "Double Valve": "ORG", "Kim Ross": "PERSON"}

    def detect(self, text):
        from privatier.detect.base import Span

        return [
            Span(m.start(), m.end(), etype, word, "ner", 0.9)
            for word, etype in self.GUESSES.items()
            for m in re.finditer(rf"(?<!\w){re.escape(word)}(?!\w)", text)
        ]


def test_the_ai_is_only_asked_about_real_free_text_in_tables(tmp_path):
    from privatier.detect import PatternDetector

    src = tmp_path / "Studie"
    src.mkdir()
    header = "ID;Arm;Visit;Diagnosis;Notes\n"
    rows = "".join(
        f"P{i};Placebo;T0;Aortic Stenosis;Note number {i} from the ward\n" for i in range(25)
    ) + "P99;Placebo;T0;Aortic Stenosis;Kim Ross called the ward\n"
    (src / "Double_Valve.csv").write_text(header + rows, encoding="utf-8")
    anonymize_folder(src, PASSWORD, detectors=[PatternDetector(), EagerAI()])
    out = tmp_path / "Studie_anonymized" / "Double_Valve.csv"
    assert out.exists()
    lines = out.read_text(encoding="utf-8-sig").splitlines()
    assert lines[1].split(";")[1:4] == ["Placebo", "T0", "Aortic Stenosis"]
    assert "Kim Ross" not in lines[-1] and "called the ward" in lines[-1]


# --- surgery dates stay granular ---------------------------------------------------
@pytest.mark.parametrize("header", ["Surgery date", "OP Datum", "date_surgery", "dateofsurgery", "Dateofrehospitalization", "Date of FU/ date of death", "Sterbedatum"])
def test_dates_other_than_birth_dates_keep_day_and_month(tmp_path, header):
    rows = [["Patient ID", header, "Note"]]
    rows += [[f"P{i}", dt.datetime(2020, 2, i + 1) if i % 2 else f"{i + 1}.3.2021", "ok"] for i in range(6)]
    summary = anonymize_folder(excel(tmp_path, rows), PASSWORD)
    result = output_rows(tmp_path)
    assert [r[1] for r in result[1:]] == [r[1] for r in rows[1:]]
    assert summary.warnings == []  # keeping them is the rule, not a question
    assert any("kept with day and month" in note for note in summary.notes)


def test_spss_surgery_date_keeps_day_and_month(tmp_path):
    src = tmp_path / "Studie"
    src.mkdir()
    df = pd.DataFrame({"pat_id": [1000.0, 1001.0], "date_surgery": pd.to_datetime(["2020-02-03", "2021-05-06"])})
    pyreadstat.write_sav(df, str(src / "a.sav"))
    anonymize_folder(src, PASSWORD)
    out, _ = pyreadstat.read_sav(str(tmp_path / "Studie_anonymized" / "a.sav"))
    assert out["date_surgery"].iloc[0] == pd.Timestamp("2020-02-03")


def test_free_text_dates_are_still_replaced(tmp_path):
    out, _ = run(tmp_path, {"a.csv": "Patient ID;Notes\nP1;Called on 03.04.2021 about results\n"})
    assert "03.04.2021" not in table(out, "a.csv")[1][1]


# --- does a birth date column hold birth dates? ------------------------------------
def birth_table(tmp_path, births, surgeries=None, ages=None):
    rows = [["Patient ID", "Date of birth"] + (["Surgery date"] if surgeries else []) + (["Age"] if ages else [])]
    for i, born in enumerate(births):
        row = [f"P{i}", born]
        if surgeries:
            row.append(surgeries[i])
        if ages:
            row.append(ages[i])
        rows.append(row)
    return anonymize_folder(excel(tmp_path, rows), PASSWORD)


def d(year, month=6, day=15):
    return dt.datetime(year, month, day)


def test_real_looking_birth_dates_raise_no_question(tmp_path):
    births = [d(1950 + i) for i in range(8)]
    surgeries = [d(2020) for _ in range(8)]
    ages = [70 - i for i in range(8)]
    summary = birth_table(tmp_path, births, surgeries, ages)
    assert summary.warnings == []


def test_birth_date_column_holding_the_same_dates_as_another_column(tmp_path):
    dates = [d(2010 + i) for i in range(8)]
    summary = birth_table(tmp_path, dates, list(dates))
    assert any("called a birth date" in n and "same dates" in n and "column C" in n for _, n in summary.warnings)
    assert output_rows(tmp_path)[1][1] == 2010  # still protected until the user corrects the header


def test_mislabelled_birth_date_is_found_across_sheets(tmp_path):
    src = tmp_path / "Studie"
    src.mkdir()
    wb = Workbook()
    first = wb.active
    first.title = "Genese"
    first.append(["dob", "numbering"])
    second = wb.create_sheet("Prothesis")
    second.append(["Geb.Datum", "OP Datum", "numbering"])
    for i in range(8):
        first.append([d(2010 + i), i])
        second.append([d(1950 + i), d(2010 + i), i])
    wb.save(src / "a.xlsx")
    summary = anonymize_folder(src, PASSWORD)
    notes = [n for _, n in summary.warnings if "called a birth date" in n]
    assert len(notes) == 1 and "Genese, column A" in notes[0] and "Prothesis, column B" in notes[0]


def test_birth_date_after_surgery_is_flagged_with_a_count(tmp_path):
    births = [d(1950 + i) for i in range(8)]
    births[0] = d(2022)
    summary = birth_table(tmp_path, births, [d(2020) for _ in range(8)])
    assert any("in 1 row(s) the birth date comes after" in n for _, n in summary.warnings)


def test_birth_dates_in_the_future_or_too_long_ago(tmp_path):
    births = [d(1950 + i) for i in range(6)] + [d(2999), d(1800)]
    summary = birth_table(tmp_path, births)
    notes = " ".join(n for _, n in summary.warnings)
    assert "1 date(s) lie in the future" in notes and "older than 120" in notes


def test_birth_dates_that_do_not_fit_the_age_column(tmp_path):
    births = [d(2000 + i) for i in range(8)]
    summary = birth_table(tmp_path, births, [d(2020) for _ in range(8)], [75] * 8)
    assert any("does not fit the age column" in n for _, n in summary.warnings)


def test_age_at_surgery_fits_even_though_it_was_long_ago(tmp_path):
    births = [d(1950) for _ in range(8)]
    summary = birth_table(tmp_path, births, [d(2000) for _ in range(8)], [50] * 8)
    assert summary.warnings == []


def test_too_few_values_are_not_judged(tmp_path):
    summary = birth_table(tmp_path, [d(2010), d(2011)], [d(2010), d(2011)])
    assert summary.warnings == []


def test_question_about_birth_dates_holds_no_values(tmp_path):
    dates = [d(2010 + i) for i in range(8)]
    summary = birth_table(tmp_path, dates, list(dates))
    assert "2010" not in " ".join(n for _, n in summary.warnings)


# --- stored formula results --------------------------------------------------------
def excel_with_results(tmp_path, rows, results, name="a.xlsx", sheets=None):
    """A file as Excel would save it: formulas with their stored results."""
    from privatier.handlers.excel_formulas import write_stored_results

    src = tmp_path / "Studie"
    src.mkdir(exist_ok=True)
    wb = Workbook()
    wb.active.title = "Daten"
    for row in rows:
        wb.active.append(row)
    for title, sheet_rows in (sheets or {}).items():
        extra = wb.create_sheet(title)
        for row in sheet_rows:
            extra.append(row)
    wb.save(src / name)
    write_stored_results(src / name, results)
    return src


def stored_values(tmp_path, name="a.xlsx", sheet=0):
    return load_workbook(tmp_path / "Studie_anonymized" / name, data_only=True).worksheets[sheet]


def test_formula_results_survive_for_tools_that_do_not_recalculate(tmp_path):
    rows = [["Patient ID", "Weight", "Height", "BMI", "Obese", "Label", "Flag"]]
    rows += [["P1", 90, 1.8, "=B2/C2^2", '=IF(D2>=30,1,0)', '=IF(E2=1,"high","normal")', "=E2=1"]]
    results = [{"D2": (None, "27.7"), "E2": (None, "0"), "F2": ("str", "normal"), "G2": ("b", "0")}]
    src = excel_with_results(tmp_path, rows, results)
    summary = anonymize_folder(src, PASSWORD)
    sheet = stored_values(tmp_path)
    assert sheet["D2"].value == 27.7 and sheet["E2"].value == 0
    assert sheet["F2"].value == "normal" and sheet["G2"].value is False
    assert load_workbook(tmp_path / "Studie_anonymized" / "a.xlsx").active["D2"].value == "=B2/C2^2"
    assert summary.warnings == []
    frame = pd.read_excel(tmp_path / "Studie_anonymized" / "a.xlsx")
    assert frame["BMI"].iloc[0] == 27.7  # what Python, R and AI tools read


def test_stored_date_result_stays_a_date(tmp_path):
    from openpyxl.styles import numbers

    rows = [["Patient ID", "Surgery date", "Control date"], ["P1", dt.datetime(2020, 1, 1), "=B2+30"]]
    src = excel_with_results(tmp_path, rows, [{"C2": (None, "43861")}])
    wb = load_workbook(src / "a.xlsx")
    wb.active["C2"].number_format = numbers.FORMAT_DATE_YYYYMMDD2
    wb.save(src / "a.xlsx")
    from privatier.handlers.excel_formulas import write_stored_results

    write_stored_results(src / "a.xlsx", [{"C2": (None, "43861")}])
    anonymize_folder(src, PASSWORD)
    assert stored_values(tmp_path)["C2"].value == dt.datetime(2020, 1, 31)


@pytest.mark.parametrize(
    "formula, stored",
    [("=C2", (None, "27526")), ("=C2+1", (None, "27527")), ("=YEAR(C2)", (None, "1975")), ('=A2&" "&B2', ("str", "Mark Long")),
     ("=SUM(A2:D2)", (None, "1")), ("=SUM(C:C)", (None, "1"))],
)
def test_results_that_depend_on_identifying_columns_are_not_kept(tmp_path, formula, stored):
    rows = [["Vorname", "Nachname", "Geburtsdatum", "Score", "Result"], ["Mark", "Long", dt.datetime(1975, 5, 12), 5, formula]]
    src = excel_with_results(tmp_path, rows, [{"E2": stored}])
    summary = anonymize_folder(src, PASSWORD)
    assert stored_values(tmp_path)["E2"].value is None
    assert any("column E" in note and "stored results were removed" in note for _, note in summary.warnings)


def test_results_depending_on_identifying_columns_through_other_formulas(tmp_path):
    rows = [["Geburtsdatum", "Step", "Next", "Other", "Fine"], [dt.datetime(1975, 5, 12), "=A2", "=B2", 5, "=D2*2"]]
    src = excel_with_results(tmp_path, rows, [{"B2": (None, "27526"), "C2": (None, "27526"), "E2": (None, "10")}])
    anonymize_folder(src, PASSWORD)
    sheet = stored_values(tmp_path)
    assert sheet["B2"].value is None and sheet["C2"].value is None and sheet["E2"].value == 10


def test_results_depending_on_identifying_columns_on_another_sheet(tmp_path):
    rows = [["Score", "From other sheet"], [1, "=Stamm!A2"]]
    sheets = {"Stamm": [["Geburtsdatum", "Score"], [dt.datetime(1975, 5, 12), 7]]}
    results = [{"B2": (None, "27526")}, {}]
    src = excel_with_results(tmp_path, rows, results, sheets=sheets)
    anonymize_folder(src, PASSWORD)
    assert stored_values(tmp_path)["B2"].value is None


@pytest.mark.parametrize("formula", ["=[1]Sheet1!A1", "=Patient_DOB", "=SUM(Table1[DOB])"])
def test_results_that_cannot_be_traced_are_not_kept(tmp_path, formula):
    rows = [["Score", "Result"], [1, formula]]
    src = excel_with_results(tmp_path, rows, [{"B2": (None, "27526")}])
    anonymize_folder(src, PASSWORD)
    assert stored_values(tmp_path)["B2"].value is None


def test_text_results_are_checked_like_any_other_text(tmp_path):
    rows = [["Score", "Label"], [1, '=IF(A2=1,"Patient Mark Long","x")']]
    src = excel_with_results(tmp_path, rows, [{"B2": ("str", "Patient Mark Long")}])
    anonymize_folder(src, PASSWORD)
    sheet = stored_values(tmp_path)
    assert "Long" not in sheet["B2"].value and sheet["B2"].value.startswith("Patient PERSON_")


def test_excluded_function_names_are_not_read_as_cells(tmp_path):
    from privatier.handlers.excel_formulas import references

    assert references("=LOG10(D2)") == [(None, 4)]
    assert references('=IF(A1>2,"A1 text",B$3)') == [(None, 1), (None, 2)]
    assert references("='Other Sheet'!$C$1+Stamm!D2") == [("Other Sheet", 3), ("Stamm", 4)]
    assert references("=A1:C2") == [(None, 1), (None, 2), (None, 3)]
    assert references("=TRUE") == []
    assert references("=MyName+1") is None


def test_formula_follows_a_renamed_sheet(tmp_path):
    src = tmp_path / "Studie"
    src.mkdir()
    wb = Workbook()
    wb.active.title = "Frau Max Müller"
    wb.active.append(["Score"])
    wb.active.append([5])
    other = wb.create_sheet("Auswertung")
    other.append(["Result"])
    other.append(["='Frau Max Müller'!A2"])
    wb.save(src / "a.xlsx")
    anonymize_folder(src, PASSWORD)
    result = load_workbook(tmp_path / "Studie_anonymized" / "a.xlsx")
    assert "Müller" not in result.worksheets[0].title
    assert "Müller" not in result["Auswertung"]["A2"].value and result.worksheets[0].title in result["Auswertung"]["A2"].value


def test_restore_keeps_stored_results(tmp_path):
    rows = [["Patient ID", "Weight", "Double"], ["P1", 90, "=B2*2"]]
    src = excel_with_results(tmp_path, rows, [{"C2": (None, "180")}])
    anonymize_folder(src, PASSWORD)
    restored = round_trip(tmp_path, tmp_path / "Studie_anonymized")
    sheet = load_workbook(restored / "a.xlsx", data_only=True).active
    assert sheet["A2"].value == "P1" and sheet["C2"].value == 180


def test_numbers_keep_every_digit(tmp_path):
    """The library that writes Excel files rounds to 16 digits; the original had 17."""
    from privatier.handlers.excel_formulas import read_exact_numbers

    src = tmp_path / "Studie"
    src.mkdir()
    wb = Workbook()
    for row in [["Patient ID", "Geburtsjahr", "esvi"], ["P1", 1975, 1.0], ["P2", 1980, 2.0]]:
        wb.active.append(row)
    wb.save(src / "a.xlsx")
    # Write 17 digits the way Excel does.
    import zipfile

    source = src / "a.xlsx"
    with zipfile.ZipFile(source) as z:
        parts = {i.filename: z.read(i.filename) for i in z.infolist()}
    sheet = "xl/worksheets/sheet1.xml"
    assert b"<v>1</v>" in parts[sheet]
    parts[sheet] = parts[sheet].replace(b"<v>1</v>", b"<v>41.123456789012345</v>", 1)
    with zipfile.ZipFile(source, "w") as z:
        for name, data in parts.items():
            z.writestr(name, data)
    anonymize_folder(src, PASSWORD)
    out = tmp_path / "Studie_anonymized" / "a.xlsx"
    assert read_exact_numbers(out)[0]["C2"] == "41.123456789012345"
    assert load_workbook(out).active["C2"].value == load_workbook(source).active["C2"].value


def test_replaced_numbers_are_not_put_back(tmp_path):
    rows = [["Patient ID", "Geburtsdatum", "Score"], [100123, dt.datetime(1975, 5, 12), 5]]
    anonymize_folder(excel(tmp_path, rows), PASSWORD)
    result = output_rows(tmp_path)
    assert result[1][0].startswith("ID_") and result[1][1] == 1975 and result[1][2] == 5


def test_ai_finding_in_free_text_does_not_spread_to_categories_or_labels(tmp_path):
    from privatier.detect import PatternDetector
    from privatier.detect.base import Span

    class DeviceAI:
        name = "ner"

        def detect(self, text):
            at = text.find("Mitra Clip")
            return [] if at < 0 else [Span(at, at + 10, "ORG", "Mitra Clip", "ner", 0.9)]

    rows = "".join(f"P{i};Mitra Clip;Note {i} about the valve from Mitra Clip today\n" for i in range(25))
    out, _ = run(tmp_path, {"a.csv": "ID;Klappe;Notes\n" + rows}, detectors=[PatternDetector(), DeviceAI()])
    lines = table(out, "a.csv")
    assert lines[1][1] == "Mitra Clip" and "Mitra Clip" not in lines[1][2]


def test_name_from_a_table_still_reaches_a_category_column(tmp_path):
    rows = "".join(f"P{i};Tom Berg;Tom Berg;x\n" for i in range(3))
    out, _ = run(tmp_path, {"a.csv": "ID;Name;Betreuer;Score\n" + rows})
    assert "Berg" not in str(table(out, "a.csv"))


def test_fragment_of_a_name_does_not_spread(tmp_path):
    out, _ = run(
        tmp_path,
        {"a.txt": "Rückfrage bei Dr. St. wegen Befund.\n", "b.csv": "ID;Klappe\n" + "".join(f"P{i};St. Jude Medical\n" for i in range(5))},
    )
    assert table(out, "b.csv")[1][1] == "St. Jude Medical"


def test_codes_glued_to_a_word_are_restored(tmp_path):
    text = "ECV12.3.2015 ok, 8.1.2018Reflux, siehe Z.n.3.4.2019\n"
    out, _ = run(tmp_path, {"a.txt": text})
    assert "12.3.2015" not in (out / "a.txt").read_text(encoding="utf-8")
    restored = round_trip(tmp_path, out)
    assert (restored / "a.txt").read_text(encoding="utf-8") == text


def test_plain_words_like_codes_are_left_alone_on_restore():
    p = Pseudonymizer()
    from privatier.transform import Restorer

    assert Restorer(p).text("UPDATE_0001 and DATE_9999") == "UPDATE_0001 and DATE_9999"


@pytest.mark.parametrize("marker", ["NA", "n.a.", "-", "?", "unknown", "k.A."])
def test_no_value_markers_stay_and_are_not_people(tmp_path, marker):
    out, summary = run(
        tmp_path,
        {"a.csv": f"Patient ID;Name;Geburtsdatum;Investigator\n{marker};{marker};{marker};{marker}\nP1;Ana Ruiz;01.02.1980;Dr. Pohl\n"},
    )
    assert table(out, "a.csv")[1] == [marker, marker, marker, marker]
    assert "Ruiz" not in str(table(out, "a.csv")[2])


def test_the_surname_na_is_not_a_no_value_marker(tmp_path):
    out, _ = run(tmp_path, {"a.csv": "Name;Geburtsdatum\nNa;01.02.1980\n"})
    assert table(out, "a.csv")[1][0].startswith("PERSON_")
