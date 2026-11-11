"""An English test, tables first. All invented. Every clinical cell must come out unchanged.

    python tools/hard_data_en.py [--ai]
"""
import csv
import datetime as dt
import io
import shutil
import sys
import tempfile
from pathlib import Path

from openpyxl import Workbook, load_workbook

from privatier.engine import anonymize_folder

use_ai = "--ai" in sys.argv
work = Path(tempfile.mkdtemp(prefix="english_"))
src = work / "Trial"
src.mkdir()

# name, surname, DOB, MRN, person. Two John Smiths told apart by birth date, two with the same year.
PEOPLE = [
    ("John", "Smith", "03/14/1955", "MRN1001", "john55"), ("John", "Smith", "11/02/1967", "MRN1002", "john67"),
    ("Mary", "Long", "01/23/1980", "MRN1003", "mary_jan"), ("Mary", "Long", "09/30/1980", "MRN1004", "mary_sep"),
    ("Grace", "White", "07/19/1949", "MRN1005", "grace"), ("Mark", "Young", "05/25/1971", "MRN1006", "mark"),
    ("Siobhan", "O'Brien", "12/24/1962", "MRN1007", "siobhan"), ("Chinedu", "Okafor", "08/16/1988", "MRN1008", "chinedu"),
    ("Wei", "Zhang", "06/21/1990", "MRN1009", "wei"), ("Hope", "May", "04/28/1975", "MRN1010", "hope"),
]
buffer = io.StringIO()
writer = csv.writer(buffer, lineterminator="\n")
writer.writerow(["TRIAL-42 enrolment export", "", "", "", "", "", "", "", "", "", ""])
writer.writerow(["Exported 03/04/2024 by Dr. Priya Sharma", "", "", "", "", "", "", "", "", "", ""])
writer.writerow(["MRN", "Forename", "Surname", "D.O.B.", "Sex", "Arm", "Post code", "Telephone", "GP", "HbA1c", "Comments"])
for i, (first, last, dob, mrn, _) in enumerate(PEOPLE):
    writer.writerow([mrn, first, last, dob, "F" if i % 2 else "M", "Placebo" if i % 2 else "Active", "SW1A 1AA", f"020 7946 09{i:02d}",
                     "Dr. Alan Reid", f"{6 + i / 10:.1f}", "White blood cells normal; Long term follow-up" if i % 3 == 0 else "stable"])
(src / "enrolment.csv").write_text(buffer.getvalue(), encoding="utf-8")

wb = Workbook()
ws = wb.active
ws.title = "Baseline"
ws.append(["Study ID", "Patient Name", "Date of Birth", "Age", "BMI", "LVEF (%)", "NYHA", "Surgery date", "Treatment", "Surgeon"])
ws.append(["(text)", "(text)", "(mm/dd/yyyy)", "(y)", "(kg/m2)", "(%)", "(1-4)", "(mm/dd/yyyy)", "(1=repair,2=replacement)", "(text)"])
for i, (first, last, dob, mrn, _) in enumerate(PEOPLE):
    ws.append([f"S{i:03d}", f"{last}, {first}", dt.datetime.strptime(dob, "%m/%d/%Y"), 40 + i, 24.5 + i, 55 - i, 1 + i % 4,
               dt.datetime(2023, 1, 5 + i) if i % 2 else f"1/{5 + i}/2023", 1 + i % 2, "Mr. Daniel Kerr"])
followup = wb.create_sheet("Follow up")
followup.append(["Study ID", "Visit date", "EF", "Mortality", "Notes"])
for i in range(10):
    followup.append([f"S{i:03d}", dt.datetime(2024, 2, 1 + i), 50 + i, 0, "Seen by Nurse Kelly Moore" if i == 2 else "Kaplan-Meier cohort"])
names_only = wb.create_sheet("Names only")
names_only.append(["Name", "Score"])
for name, score in [("Grace White", 1), ("Grace White", 2), ("Tom Reed", 3), ("Tom Reed", 4)]:
    names_only.append([name, score])
wb.save(src / "baseline.xlsx")

summary = anonymize_folder(src, "english password", use_ai=use_ai)
out = work / "Trial_pseudonymised"

rows = list(csv.reader(io.StringIO((out / "enrolment.csv").read_text(encoding="utf-8-sig"))))
result = load_workbook(out / "baseline.xlsx")
base, fu, no = result["Baseline"], result["Follow up"], result["Names only"]
everything = "\n".join(",".join(r) for r in rows) + "\n" + "\n".join(
    " | ".join("" if v is None else str(v) for v in r) for s in result.worksheets for r in s.iter_rows(values_only=True)
)

problems = 0
for value in ("John", "Smith", "Mary Long", "Long, Mary", "Grace", "White, ", "Mark", "Young", "Siobhan", "O'Brien", "Chinedu", "Okafor", "Wei", "Zhang",
              "Hope", "May,", "Priya", "Sharma", "Alan", "Reid", "Daniel", "Kerr", "Kelly", "Moore", "Tom", "Reed", "MRN100",
              "SW1A", "020 7946", "03/14/1955", "11/02/1967", "1955-03-14", "S001"):
    if value in everything:
        problems += 1
        print("LEAK", repr(value))
for value in ("White blood cells normal", "Long term follow-up", "Kaplan-Meier cohort", "Placebo", "Active", "Forename", "D.O.B.", "Post code", "(mm/dd/yyyy)",
              "(1=repair,2=replacement)", "Surgery date", "Mortality", "1/5/2023"):
    if value not in everything:
        problems += 1
        print("DAMAGED", repr(value))

base_code = lambda v: "_".join(str(v).split("_")[:2])
at = next(i for i, r in enumerate(rows) if r[0] == "MRN")
for sheet_row, row, person in zip(base.iter_rows(min_row=3, values_only=True), rows[at + 1 :], PEOPLE):
    if base_code(sheet_row[1]) != base_code(row[1]):
        problems += 1
        print("SPLIT across files", person[4], base_code(row[1]), base_code(sheet_row[1]))
    for original, new in ((6.0 + 0, None),):
        pass
codes = [base_code(r[1]) for r in rows[at + 1 :]]
if len(set(codes)) != len(PEOPLE):
    problems += 1
    print("MERGED", codes)
clinical_ok = all(r[3:7] == (40 + i, 24.5 + i, 55 - i, 1 + i % 4) for i, r in enumerate(base.iter_rows(min_row=3, values_only=True)))
print("clinical cells unchanged:", clinical_ok)
problems += not clinical_ok
same_id = all(a[0] == b[0] for a, b in zip(base.iter_rows(min_row=3, values_only=True), fu.iter_rows(min_row=2, values_only=True)))
print("Study ID links both sheets:", same_id)
problems += not same_id
no_rows = list(no.iter_rows(min_row=2, values_only=True))
print("names with no evidence kept apart:", no_rows[0][0] != no_rows[1][0], "| not linked to the patient Grace White:", base_code(no_rows[0][0]) not in codes)
problems += no_rows[0][0] == no_rows[1][0] or base_code(no_rows[0][0]) in codes
print("errors:", summary.errors)
print("QUESTIONS:")
from privatier.cli import _grouped_questions

for line in _grouped_questions(summary.warnings):
    print("  -", line)
print("TOTAL PROBLEMS:", problems)
shutil.rmtree(work)
sys.exit(1 if problems else 0)
