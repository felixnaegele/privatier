"""One person gets one code, two people never share one, and no information is lost."""

import datetime as dt
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
    assert any("same name" in note for _, note in summary.warnings)


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


def test_surname_links_to_the_one_person_in_the_same_document(tmp_path):
    out, _ = run(tmp_path, {"a.txt": "Patientin Anna Schmidt, geb. 12.05.1975. Frau Schmidt war zufrieden.\n"})
    text = (out / "a.txt").read_text(encoding="utf-8")
    assert "Patientin PERSON_0001," in text and "Frau PERSON_0001_L " in text


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


def test_file_names_are_restored(tmp_path):
    src = tmp_path / "Studie"
    src.mkdir()
    (src / "Akte_Patient Anna Schmidt.txt").write_text("Patientin Anna Schmidt", encoding="utf-8")
    anonymize_folder(src, PASSWORD)
    restored = round_trip(tmp_path, tmp_path / "Studie_anonymized")
    assert [p.name for p in restored.iterdir()] == ["Akte_Patient Anna Schmidt.txt"]


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
