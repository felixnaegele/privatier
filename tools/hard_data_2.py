"""Second hard test, written after the first round of fixes: new invented names and layouts. Usage: python tools/hard_data_2.py [--ai]"""
import csv
import datetime as dt
import io
import shutil
import sys
import tempfile
from pathlib import Path

from docx import Document
from openpyxl import Workbook, load_workbook

from privatier.engine import anonymize_folder

PW = "holdout password"
use_ai = "--ai" in sys.argv
work = Path(tempfile.mkdtemp(prefix="hold_"))
src = work / "Projekt"
(src / "roh").mkdir(parents=True)
(src / "Korrespondenz").mkdir()

# Tab-separated, comma-style names in two columns, German month dates, Latin-1 encoding
(src / "roh" / "aufnahmen.tsv").write_bytes(
    (
        "Familienname\tRufname\tGeburtstag\tSexus\tKasse\tVersicherten-Nr\tHausärztin\tVerlauf\n"
        "Schäfer\tJürgen\t7. März 1949\tm\tAOK\tN112233445\tDr. Roswitha Engel\tSchäfer berichtet über Besserung\n"
        "Schäfer\tJürgen\t19. Juli 1971\tm\tTK\tP223344556\tDr. Roswitha Engel\tVater von Jürgen Schäfer (geb. 1971)?\n"
        "Krüger\tGünther\t01.01.1950\tm\tDAK\tQ334455667\tDr. Roswitha Engel\tGünther lebt allein in Oldenburg\n"
        "Dąbrowski\tŁukasz\t1983-10-02\tm\tTK\tR445566778\tProf. Nuri Yıldız\tSpricht wenig Deutsch; Bruder Marek hilft\n"
    ).encode("utf-8")
)
# Excel: header on row 5, no title formatting, name in English headers, DOB as text and as number-like date
wb = Workbook()
ws = wb.active
ws.title = "Tabelle1"
for _ in range(2):
    ws.append([])
ws.append(["Projekt ALPHA, PI: Prof. Nuri Yıldız"])
ws.append([])
ws.append(["subject_id", "patient_name", "dob", "visit", "arm", "bmi"])
ws.append(["S-001", "Krüger, Günther", dt.datetime(1950, 1, 1), dt.datetime(2023, 5, 2), "Placebo", 27.1])
ws.append(["S-002", "Schaefer, Juergen", "07/03/1949", dt.datetime(2023, 5, 3), "Verum", 31.0])
ws.append(["S-003", "Schaefer, Juergen", "19/07/1971", dt.datetime(2023, 5, 4), "Placebo", 24.4])
ws.append(["S-004", "Hannah Berger", None, dt.datetime(2023, 5, 5), "Verum", 22.8])
wb.save(src / "roh" / "alpha.xlsx")

# Prose with hard grammar and tricky words
(src / "Korrespondenz" / "Verlauf_Berger.txt").write_text(
    "Betr.: Hannah Berger, *24.06.1990, Fall-Nr. 2023/77812\n\n"
    "Die 33-jährige Frau Berger kam gemeinsam mit ihrer Mutter Ingeborg Berger in die Ambulanz am Klinikum Weserbogen. "
    "Berger-Krankheit ist auszuschließen. Ihr Lebensgefährte Tobias wartete draußen. "
    "Nach Rücksprache mit OA Dr. Falk empfahlen wir eine Sonographie nach Bosniak. "
    "Das Blumberg-Zeichen war negativ, der Babinski-Reflex unauffällig, Apgar nicht relevant. "
    "Die Patientin wohnt in der Goethestraße 7 in 26121 Oldenburg, Handy 0160 5550199. "
    "Sie arbeitet bei der Firma Nordsee Fisch GmbH.\n\n"
    "Sohn: Ben Berger, geb. 2015.\n"
    "Im Juli geht es zur Reha. Am Ende des Mai bitte Kontrolle. Herbst und Winter waren schwierig.\n\n"
    "gez. Dr. med. M. Falk\n",
    encoding="utf-8",
)
(src / "Korrespondenz" / "kurz.txt").write_text(
    "Frau Engel ruft an: Hr. Krügers Tochter Anke möchte Befund.\n"
    "Pat. Yıldırım, Emine, geb. 11.04.1966 - KV-Nr. S556677889.\n"
    "Telefonat m. Herrn Dr. Otto am 3.5.23, Fax 0441/555 0177.\n"
    "E-Mail an anke.krueger@web.example verschickt.\n"
    "Bei Fr. Dąbrowski (Ehefrau) nachfragen.\n",
    encoding="utf-8",
)
doc = Document()
doc.add_paragraph("Einwilligung")
table = doc.add_table(rows=3, cols=2)
for r, (a, b) in enumerate([("Name, Vorname", "Sommer, Greta"), ("Geburtsdatum", "30.09.1958"), ("Teilnehmer-Nr.", "T-4471")]):
    table.cell(r, 0).text = a
    table.cell(r, 1).text = b
doc.add_paragraph("Ich, Greta Sommer, stimme zu. Im Sommer 2023 fand die Erhebung statt.")
doc.save(src / "Korrespondenz" / "Einwilligung_Sommer_Greta.docx")

summary = anonymize_folder(src, PW, use_ai=use_ai)
out = work / "Projekt_pseudonymised"

texts = {}
for p in out.rglob("*"):
    if p.is_file():
        if p.suffix == ".xlsx":
            b = load_workbook(p)
            rows = [" | ".join("" if v is None else str(v) for v in r) for s in b.worksheets for r in s.iter_rows(values_only=True)]
            texts[str(p.relative_to(out))] = "\n".join(rows)
        elif p.suffix == ".docx":
            d = Document(p)
            lines = [x.text for x in d.paragraphs] + [" | ".join(c.text for c in r.cells) for t in d.tables for r in t.rows]
            texts[str(p.relative_to(out))] = "\n".join(lines)
        else:
            texts[str(p.relative_to(out))] = p.read_text(encoding="utf-8-sig")

MUST_GO = ["Schäfer", "Schaefer", "Jürgen", "Juergen", "Krüger", "Günther", "Dąbrowski", "Łukasz", "Roswitha", "Engel",
           "Yıldız", "Nuri", "Marek", "Hannah", "Berger,", "Frau Berger", "Ingeborg", "Ben Berger", "Tobias", "Falk",
           "Yıldırım", "Emine", "Anke", "anke.krueger", "Otto", "Greta", "Sommer,", "Hr. Krüger",
           "7. März 1949", "19. Juli 1971", "07/03/1949", "19/07/1971", "24.06.1990", "11.04.1966", "30.09.1958",
           "N112233445", "S556677889", "T-4471", "S-001", "S-004", "2023/77812", "Goethestraße", "26121", "0160 5550199",
           "0441/555 0177", "Weserbogen", "Nordsee Fisch", "Oldenburg"]
MUST_STAY = ["Berger-Krankheit", "Blumberg-Zeichen", "Babinski-Reflex", "Sonographie nach Bosniak", "Apgar", "Im Juli",
             "Ende des Mai", "Herbst und Winter", "Im Sommer 2023", "33-jährige", "Placebo", "Verum", "Ambulanz",
             "Familienname", "Rufname", "Geburtstag", "subject_id", "patient_name", "Einwilligung", "Hausärztin",
             "AOK", "TK", "Name, Vorname", "Teilnehmer-Nr.", "Reha", "Verlauf"]

print("MODE:", "AI" if use_ai else "rules only")
leaks = {v: sorted({k.split(" [")[0] for k, t in texts.items() if v in t}) for v in MUST_GO if any(v in t for t in texts.values())}
print(f"LEAKS {len(leaks)}/{len(MUST_GO)}")
for v, f in leaks.items():
    print("  ", repr(v), f)
gone = [v for v in MUST_STAY if not any(v in t for t in texts.values())]
print(f"DAMAGE {len(gone)}/{len(MUST_STAY)}:", gone)

tsv = list(csv.reader(io.StringIO(next(out.glob("roh/*.tsv")).read_text(encoding="utf-8-sig")), delimiter="\t"))
print("TSV head:", tsv[0])
for r in tsv[1:]:
    print("  ", r)
print("XLSX:")
for r in load_workbook(next(out.glob("roh/*.xlsx"))).active.iter_rows(min_row=3, values_only=True):
    print("  ", r)
for name in ("Korrespondenz/Verlauf*", "Korrespondenz/kurz*"):
    print("---", name)
    print(next(out.glob(name)).read_text(encoding="utf-8"))
print("---", [str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()])
print("docx:", texts[next(k for k in texts if k.endswith(".docx"))])
print("errors:", summary.errors)
for f, w in summary.warnings:
    print("  check:", f, "|", w)
shutil.rmtree(work)
