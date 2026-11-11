"""The four privacy levels, the check behind the label, and answering questions. Mock data only."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pyreadstat
import pytest
from docx import Document
from openpyxl import Workbook, load_workbook

from privatier.engine import anonymize_folder, scan_folder
from privatier.identity import Decisions
from privatier.uniqueness import check_folder

PASSWORD = "testpass123"


def people(n=40):
    """A table where sex and age band are shared, but exact dates are not."""
    rows = []
    for i in range(n):
        rows.append(
            {
                "Patient ID": f"P{i:04d}",
                "Name": f"Anna{chr(65 + i % 26)} Muster{chr(65 + (i // 26))}",
                "Geburtsdatum": dt.datetime(1950 + i % 5, 1 + i % 12, 1 + i % 28),
                "Alter": 60 + i % 5,
                "Geschlecht": "m" if i % 2 else "w",
                "OP Datum": dt.datetime(2015, 1 + i % 12, 1 + i % 28),
                "Hb": 10.5 + i,
                "Bemerkung": f"Patientin klagte am Tag {i} ueber Beschwerden nummer {i}",
            }
        )
    return rows


def write_xlsx(path, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(list(rows[0]))
    for row in rows:
        ws.append(list(row.values()))
    wb.save(path)


def read_xlsx(path):
    rows = list(load_workbook(path, data_only=True).active.iter_rows(values_only=True))
    return [dict(zip(rows[0], r)) for r in rows[1:]]


@pytest.fixture
def study(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    write_xlsx(folder / "a.xlsx", people())
    return folder


def run(folder, level, **kwargs):
    return anonymize_folder(folder, PASSWORD if level < 3 else "", level=level, **kwargs)


def test_level_1_is_what_it_always_was(study, tmp_path):
    summary = run(study, 1)
    row = read_xlsx(summary.output_dir / "a.xlsx")[3]
    assert row["OP Datum"] == dt.datetime(2015, 4, 4) and row["Alter"] == 63 and row["Geburtsdatum"] == 1953
    assert (tmp_path / "Studie_privatier" / "key.vault").exists()
    assert not summary.verdict.anonymous and "still personal data" in summary.verdict.label


def test_level_2_keeps_the_exact_age_and_reduces_only_dates(study, tmp_path):
    summary = run(study, 2)
    row = read_xlsx(summary.output_dir / "a.xlsx")[3]
    assert row["Alter"] == 63, "the age stays exact at level 2"
    assert row["Geburtsdatum"] == 1953
    assert row["OP Datum"] == "2015-04"
    assert row["Hb"] == 13.5
    assert row["Bemerkung"].startswith("Patientin")
    assert (tmp_path / "Studie_privatier" / "key.vault").exists()
    assert not summary.verdict.anonymous


def test_level_3_leaves_no_key_and_reduces_further(study, tmp_path):
    (study / "brief.txt").write_text("Sehr geehrte Frau Muster", encoding="utf-8")
    summary = run(study, 3)
    row = read_xlsx(summary.output_dir / "a.xlsx")[3]
    assert row["OP Datum"] == 2015 and row["Alter"] == "60-69" and row["Geburtsdatum"] == "1950-1959"
    assert row["Bemerkung"] is None and row["Hb"] == 13.5
    assert row["Patient ID"] != "P0003" and row["Patient ID"].startswith("ID_") and len(row["Patient ID"]) > 7
    assert not (tmp_path / "Studie_privatier" / "key.vault").exists()
    assert not (summary.output_dir / "brief.txt").exists()
    assert any(file == "brief.txt" for file, _ in summary.skipped)
    assert not summary.verdict.anonymous, "only level 4 can carry the word"


def test_an_old_key_does_not_fit_a_level_without_key(study, tmp_path):
    first = run(study, 1)
    old = read_xlsx(first.output_dir / "a.xlsx")[0]["Patient ID"]
    second = run(study, 4)
    assert read_xlsx(second.output_dir / "a.xlsx")[0]["Patient ID"] != old


def test_level_4_removes_dates_and_can_earn_the_label(study):
    summary = run(study, 4)
    row = read_xlsx(summary.output_dir / "a.xlsx")[3]
    assert row["OP Datum"] is None and row["Alter"] == "60-69" and row["Hb"] == 13.5
    assert summary.verdict.anonymous, summary.verdict.reasons
    assert summary.check.worst.in_small_group == 0
    assert not any("kept with day and month" in note for note in summary.notes), "it must not say what did not happen"


def test_level_4_blanks_a_patient_who_still_stands_out(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    rows = people()
    rows[5]["Alter"] = 97
    write_xlsx(folder / "a.xlsx", rows)
    summary = run(folder, 4)
    out = read_xlsx(summary.output_dir / "a.xlsx")
    assert out[5]["Alter"] is None
    assert out[6]["Alter"] == "60-69"
    assert summary.counts["BLANKED_RARE"] >= 1
    assert summary.verdict.anonymous, summary.verdict.reasons


def test_a_table_too_small_to_hide_anyone_is_blanked_and_not_passed_as_checked(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    write_xlsx(folder / "a.xlsx", people(3))
    summary = run(folder, 4)
    out = read_xlsx(summary.output_dir / "a.xlsx")
    assert all(r["Alter"] is None and r["Geschlecht"] is None for r in out)
    assert not summary.verdict.anonymous, "nothing could be compared, so the check shows nothing"


def test_no_label_when_a_name_is_in_a_file_name(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    write_xlsx(folder / "AnnaA MusterA.xlsx", people())
    summary = run(folder, 4)
    assert not summary.verdict.anonymous
    assert any("name" in reason for reason in summary.verdict.reasons)
    assert (summary.output_dir / "AnnaA MusterA.xlsx").exists(), "file names are never changed"


def test_no_label_when_free_text_was_kept_on_request(study):
    summary = run(study, 4, keep_text={("a.xlsx", "Sheet", 7)})
    assert read_xlsx(summary.output_dir / "a.xlsx")[0]["Bemerkung"]
    assert not summary.verdict.anonymous
    assert any("free text" in reason for reason in summary.verdict.reasons)


def test_a_sheet_without_a_header_is_not_counted_as_safe(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    wb = Workbook()
    for i in range(10):
        wb.active.append([dt.datetime(2015, 1, 1 + i), 60 + i])
    wb.save(folder / "a.xlsx")
    check = check_folder(folder)
    assert [t.status for t in check.tables] == ["could_not_check"]
    summary = run(folder, 4)
    assert all(v is None for row in load_workbook(summary.output_dir / "a.xlsx").active.iter_rows(values_only=True) for v in row)


def test_the_check_reads_csv_all_dates_and_counts_patients_not_rows(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    lines = ["Patient ID;Follow-up Datum"]
    for i in range(6):  # each patient has two visits on the same two dates
        lines += [f"P{i};01.02.2015", f"P{i};01.03.2016"]
    (folder / "a.csv").write_text("\n".join(lines), encoding="utf-8")
    table = check_folder(folder).tables[0]
    assert table.status == "checked" and table.unit == "patients" and table.total == 6
    assert table.singled_out == 0 and table.in_small_group == 0
    assert table.characteristics == ["Follow-up Datum"]


def test_the_check_says_rows_when_it_cannot_tell_patients(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    (folder / "a.csv").write_text("Alter;Geschlecht\n" + "\n".join(f"{60 + i};m" for i in range(8)), encoding="utf-8")
    table = check_folder(folder).tables[0]
    assert table.unit == "rows" and table.singled_out == 8


def test_csv_at_every_level(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    (folder / "a.csv").write_text(
        "Patient ID;Alter;Geschlecht;OP Datum\n" + "\n".join(f"P{i};{60 + i % 3};m;{1 + i % 28:02d}.03.2015" for i in range(30)),
        encoding="utf-8",
    )
    first = lambda s: (s.output_dir / "a.csv").read_text(encoding="utf-8").splitlines()[1].split(";")
    assert first(run(folder, 1))[1:] == ["60", "m", "01.03.2015"]
    assert first(run(folder, 2))[1:] == ["60", "m", "2015-03"]
    assert first(run(folder, 3))[1:] == ["60-69", "m", "2015"]
    assert first(run(folder, 4))[1:] == ["60-69", "m", ""]


def test_spss_at_levels_2_and_4(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    frame = pd.DataFrame(
        {
            "patient_id": [f"P{i}" for i in range(30)],
            "age": [60.0 + i % 3 for i in range(30)],
            "sex": [1.0 + i % 2 for i in range(30)],
            "date_surgery": [dt.datetime(2015, 1 + i % 12, 1 + i % 28) for i in range(30)],
            "hb": [10.25 + i for i in range(30)],
        }
    )
    pyreadstat.write_sav(frame, str(folder / "a.sav"), variable_value_labels={"sex": {1.0: "male", 2.0: "female"}})
    out, _ = pyreadstat.read_sav(str(run(folder, 2).output_dir / "a.sav"))
    assert out["age"][1] == 61 and out["date_surgery"][1] == "2015-02" and out["hb"][1] == 11.25
    summary = run(folder, 4)
    out, meta = pyreadstat.read_sav(str(summary.output_dir / "a.sav"))
    assert out["age"][1] == "60-69" and out["hb"][1] == 11.25
    assert out["date_surgery"].isna().all() or (out["date_surgery"] == "").all()
    assert meta.variable_value_labels.get("sex") == {1.0: "male", 2.0: "female"}
    assert summary.verdict.anonymous, summary.verdict.reasons


def test_a_formula_cannot_bring_the_exact_age_back(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    wb = Workbook()
    ws = wb.active
    ws.append(["Patient ID", "Geschlecht", "OP Datum", "Alter", "Doppelt"])
    for i in range(30):
        row = i + 2
        ws.append([f"P{i}", "m", dt.datetime(2015, 3, 1 + i % 28), 60 + i % 5, f"=D{row}*2"])
    ws["D2"] = "=60+0"
    wb.save(folder / "a.xlsx")
    # Give the formulas stored results, as a file saved by Excel would have.
    from privatier.handlers.excel_formulas import write_stored_results

    write_stored_results(folder / "a.xlsx", [{"D2": (None, "60"), **{f"E{i}": (None, "120") for i in range(2, 32)}}])
    out = load_workbook(run(folder, 3).output_dir / "a.xlsx", data_only=True).active
    assert out["D2"].value == "60-69"
    assert out["E2"].value is None, "this result reads the age column, so it stays out"


def test_dates_in_a_column_without_a_date_header_are_reduced_too(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    rows = people()
    for row in rows:
        row["Komplikation"] = "keine"
    rows[2]["Komplikation"] = dt.datetime(2016, 5, 17)
    write_xlsx(folder / "a.xlsx", rows)
    out = read_xlsx(run(folder, 4).output_dir / "a.xlsx")
    assert out[2]["Komplikation"] is None and out[1]["Komplikation"] == "keine"


def test_a_date_that_can_be_read_two_ways_keeps_only_the_year(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    (folder / "a.csv").write_text(
        "Patient ID;Follow-up Datum\n" + "\n".join(f"P{i};03/04/2015" for i in range(6)), encoding="utf-8"
    )
    assert (run(folder, 2).output_dir / "a.csv").read_text(encoding="utf-8").splitlines()[1].endswith(";2015")


# --------------------------------------------------------------------------- questions and answers
def letters_about_the_same_name(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    write_xlsx(folder / "a.xlsx", [{"Name": "Max Beispiel", "Hb": 11}, {"Name": "Rita Probe", "Hb": 12}])
    write_xlsx(folder / "b.xlsx", [{"Name": "Max Beispiel", "Wert": 1}, {"Name": "Rita Probe", "Wert": 2}])
    return folder


def answers(scan, **by_kind):
    decisions = Decisions()
    for question in scan.questions:
        if question.kind in by_kind:
            decisions.apply(question, by_kind[question.kind])
    return decisions


def test_one_question_per_name_and_the_answer_links_them(tmp_path):
    folder = letters_about_the_same_name(tmp_path)
    scan = scan_folder(folder)
    same = [q for q in scan.questions if q.kind == "same_name"]
    assert len(same) == 2 and "Max Beispiel" in " ".join(q.text for q in same)
    assert not list(tmp_path.glob("Studie_*")), "a scan writes nothing"
    summary = run(folder, 1, decisions=answers(scan, same_name="same"))
    a, b = read_xlsx(summary.output_dir / "a.xlsx"), read_xlsx(summary.output_dir / "b.xlsx")
    assert a[0]["Name"] == b[0]["Name"] and a[1]["Name"] == b[1]["Name"] and a[0]["Name"] != a[1]["Name"]
    assert not summary.warnings


def test_the_answer_different_keeps_them_apart_and_stops_asking(tmp_path):
    folder = letters_about_the_same_name(tmp_path)
    decisions = answers(scan_folder(folder), same_name="apart")
    summary = run(folder, 1, decisions=decisions)
    assert read_xlsx(summary.output_dir / "a.xlsx")[0]["Name"] != read_xlsx(summary.output_dir / "b.xlsx")[0]["Name"]
    assert not summary.warnings
    assert not [q for q in scan_folder(folder, decisions=decisions).questions if q.kind == "same_name"]


def test_real_names_in_questions_never_reach_the_audit_log(tmp_path):
    folder = letters_about_the_same_name(tmp_path)
    run(folder, 1)
    assert "Beispiel" not in (tmp_path / "Studie_privatier" / "audit.jsonl").read_text(encoding="utf-8")
    assert "Beispiel" not in (tmp_path / "Studie_privatier" / "privacy_report.txt").read_text(encoding="utf-8")


def test_an_unnamed_date_column_can_be_answered(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    wb = Workbook()
    ws = wb.active
    ws.append(["Patient ID", None, "Hb"])
    for i in range(8):
        ws.append([f"P{i}", dt.datetime(1950 + i, 2, 3), 11 + i])
    wb.save(folder / "a.xlsx")
    scan = scan_folder(folder)
    question = next(q for q in scan.questions if q.kind == "column")
    assert "no header" in question.text

    def second_column(value):
        decisions = Decisions()
        decisions.apply(question, value)
        out = run(folder, 1, decisions=decisions, output_dir=tmp_path / f"out_{value}")
        return list(load_workbook(out.output_dir / "a.xlsx").active.iter_rows(values_only=True))[1][1]

    assert second_column("DOB") == 1950
    assert second_column("KEEP_DATES") == dt.datetime(1950, 2, 3)
    assert str(second_column("UNSURE")).startswith("DATE_")


def test_a_mention_in_a_letter_can_be_answered(tmp_path):
    folder = tmp_path / "Studie"
    folder.mkdir()
    write_xlsx(folder / "a.xlsx", [{"Name": "Max Beispiel", "Geburtsdatum": dt.datetime(1950, 1, 2)}])
    document = Document()
    document.add_paragraph("Bericht ueber Herr Max Beispiel, geb. 02.01.1950.")
    document.add_paragraph("Herr Beispiel kam zur Kontrolle.")
    document.save(folder / "brief.docx")
    scan = scan_folder(folder)
    mention = [q for q in scan.questions if q.kind == "mention"]
    if mention:
        summary = run(folder, 1, decisions=answers(scan, mention="yes"))
        assert not any("may belong" in w for _, w in summary.warnings)


# --------------------------------------------------------------------------- what the window relies on
def test_the_app_shows_each_level_and_writes_what_it_showed(study):
    from privatier.app.service import AppSession

    session = AppSession()
    result = session.scan(str(study), False)
    preview = result["preview"]
    assert [preview[str(n)]["worst"]["percent"] for n in (1, 2)] == [100.0, 100.0]
    assert preview["4"]["worst"]["in_small_group"] == 0 and preview["4"]["anonymous"]
    assert not preview["3"]["anonymous"] and not preview["1"]["anonymous"]
    assert any(item["header"] == "Alter" for item in preview["3"]["lost"])
    assert not any(item["header"] == "Alter" for item in preview["2"]["lost"]), "age stays at level 2"
    done = session.export(4, "", {}, [], [])
    assert done["anonymous"] and done["worst"]["in_small_group"] == 0
    assert session.export(1, "short", {}, [], [])["error"]


def test_a_second_export_does_not_overwrite_the_first(study):
    from privatier.app.service import AppSession

    session = AppSession()
    session.scan(str(study), False)
    first, second = session.export(3, "", {}, [], []), session.export(3, "", {}, [], [])
    assert first["output"] != second["output"]


def test_a_ticked_column_counts_in_the_check(study):
    from privatier.app.service import AppSession

    session = AppSession()
    result = session.scan(str(study), False)
    hb = next(c for c in result["columns"] if c["header"] == "Hb")
    assert session.preview({}, [], [])["4"]["anonymous"]
    ticked = session.preview({}, [hb["ref"]], [])["4"]
    assert "Hb" in session.preview({}, [hb["ref"]], [])["1"]["worst"]["characteristics"]
    assert ticked["blanked_rows"] > 0, "every Hb value is different, so the rare ones are blanked"
    done = session.export(4, "", {}, [hb["ref"]], [])
    row = read_xlsx(Path(done["output"]) / "a.xlsx")[0]
    assert row["Hb"] is None and row["Alter"] == "60-69", "the rare value goes, the age it did not cause stays"


def test_a_single_file_is_read_on_its_own(tmp_path):
    from privatier.app.service import AppSession

    file = tmp_path / "a.txt"
    file.write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Herr Max Müller", encoding="utf-8")
    scan = AppSession().scan(str(file), False)
    assert scan["single"] is True and scan["findings"] == []
