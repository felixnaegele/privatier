"""A hard test for Privatier: messy, realistic German data with an answer key.

Everything here is invented. The answer key says which values must disappear, which
words must survive, and who is really who, so results are measured rather than judged
by eye. Never add real data to this file.

    python tools/hard_data.py          # rules only
    python tools/hard_data.py --ai     # with the local AI model
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import pyreadstat
from docx import Document
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from privatier.engine import KEY_FILE, anonymize_folder, restore_folder
from privatier.vault import load_vault

PASSWORD = "hard test password"

KIS = "daten/KIS_Export_2024.csv"
LABOR = "daten/Labor_Verlauf.xlsx"
SAV = "daten/Fragebogen.sav"


def make(root: Path) -> Path:
    for folder in ("daten", "Briefe", "Analyse", "Patienten/Schulz_Peter_12031948"):
        (root / folder).mkdir(parents=True, exist_ok=True)

    # --- Hospital export: title lines, odd headers, "Name, Vorname", Windows encoding --------
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Klinikum Nordstadt - Export KIS", "", "", "", "", "", "", "", "", "", "", "", ""])
    writer.writerow(["Erstellt am 04.03.2024 von Dr. Ingrid Vogel", "", "", "", "", "", "", "", "", "", "", "", ""])
    writer.writerow([""] * 13)
    writer.writerow(["Pat.-Nr.", "Patient", "Geb.-Datum", "Geschl.", "Straße", "PLZ", "Ort", "Versichertennr.",
                     "Aufnahme", "Diagnose (ICD)", "Station", "Hausarzt", "Bemerkung"])
    rows = [
        ("100231", "Müller, Max", "12.05.1975", "m", "Lindenallee 4", "28195", "Bremen", "A123456780",
         "02.01.2024", "E11.9", "3B", "Dr. Hannelore Fuchs", "RS mit Ehefrau Sabine Müller, Tel. 0421/5550123"),
        ("100232", "Müller, Max", "03.11.1962", "m", "Am Deich 17a", "28199", "Bremen", "B234567891",
         "05.01.2024", "I50.1", "3B", "Dr. Hannelore Fuchs", "Pat. wünscht Rückruf\nüber Sohn Tim, 0171-5550144"),
        ("100233", "Braun, Lisa", "01.03.1980", "w", "Hauptstr. 9", "27749", "Delmenhorst", "C345678902",
         "06.01.2024", "F32.1", "2A", "PD Dr. Ingrid Vogel", "Keine Auffälligkeiten"),
        ("100234", "Braun, Lisa", "09.10.1980", "w", "Hauptstr. 21", "27749", "Delmenhorst", "D456789013",
         "06.01.2024", "F32.1", "2A", "PD Dr. Ingrid Vogel", "Nicht verwandt mit Pat.-Nr. 100233"),
        ("100235", "Meier, Hans-Jürgen", "14.02.1941", "m", "Birkenweg 3", "28207", "Bremen", "E567890124",
         "08.01.2024", "I25.1", "4C", "Dr. med. Bernd Hahn", "Sohn gleichen Namens ebenfalls in Behandlung"),
        ("100236", "Meier, Hans-Jürgen", "30.06.1968", "m", "Birkenweg 3", "28207", "Bremen", "F678901235",
         "08.01.2024", "E78.0", "4C", "Dr. med. Bernd Hahn", "Vater: Pat.-Nr. 100235"),
        ("100237", "Mustermann-Kaya, Erika", "03.04.1951", "w", "Kaiserstraße 101", "28195", "Bremen", "G789012346",
         "09.01.2024", "G20.1", "1A", "Dr. Stefan Weiß", "Morbus Parkinson seit 2015"),
        ("100238", "Öztürk, Ayşe", "22.09.1977", "w", "Weserstr. 55", "28199", "Bremen", "H890123457",
         "10.01.2024", "K50.0", "2B", "Dr. Hannelore Fuchs", "Dolmetscherin: Frau Şahin"),
        ("100239", "Nguyen, Thi Lan", "07.07.1985", "w", "Ostertorsteinweg 8", "28203", "Bremen", "I901234568",
         "11.01.2024", "E05.0", "2B", "Dr. Hannelore Fuchs", "Morbus Basedow, Kontrolle in 3 Monaten"),
        ("100240", "von der Heide, Friedrich", "11.11.1939", "m", "Am Wall 2", "28195", "Bremen", "J012345679",
         "12.01.2024", "G30.1", "4A", "Dr. med. Bernd Hahn", "Morbus Alzheimer, Betreuerin Frau Kowalczyk"),
        ("100241", "Klein, Maria", "02.02.1960", "w", "Rosenweg 1", "28215", "Bremen", "K123456781",
         "15.01.2024", "E03.9", "1B", "Dr. Stefan Weiß", "Hashimoto-Thyreoiditis; Struma klein"),
        ("100242", "Weiß, Stefan", "05.05.1955", "m", "Marktplatz 6", "28195", "Bremen", "L234567892",
         "15.01.2024", "I10.0", "1B", "Dr. Hannelore Fuchs", "Nicht identisch mit Oberarzt Dr. Weiß"),
        ("100243", "Mai, Jana", "15.08.1992", "w", "Mozartstr. 12", "28203", "Bremen", "M345678903",
         "16.01.2024", "O24.4", "5A", "Dr. Hannelore Fuchs", "Termin im Mai 2024 vereinbart"),
    ]
    writer.writerows(rows)
    (root / KIS).write_bytes(buffer.getvalue().encode("utf-8-sig"))

    # --- Excel: merged title, several sheets, hidden sheet, IDs as numbers ------------------
    wb = Workbook()
    ws = wb.active
    ws.title = "Stammdaten"
    ws.append(["Studie DIAB-2 Stammdaten (vertraulich)"])
    ws.merge_cells("A1:E1")
    ws.append([])
    ws.append(["Pat-ID", "Name", "Geburtsdatum", "Geschlecht", "Gruppe"])
    ws.append([100231, "Max Mueller", dt.datetime(1975, 5, 12), "m", "Intervention"])
    ws.append([100232, "Max Müller", dt.datetime(1962, 11, 3), "m", "Kontrolle"])
    ws.append([100235, "Hans-Jürgen Meier", dt.datetime(1941, 2, 14), "m", "Kontrolle"])
    ws.append([100236, "Hans Jürgen Meier", dt.datetime(1968, 6, 30), "m", "Intervention"])
    ws.append([100244, "Zofia Kowalczyk", "20.01.1944", "w", "Intervention"])
    ws["B5"].comment = Comment("Achtung: nicht verwechseln mit Max Mueller aus Gruppe A", "Dr. Ingrid Vogel")

    labor = wb.create_sheet("Labor")
    labor.append(["Pat-ID", "Datum", "HbA1c", "Kreatinin", "Unterschrift"])
    labor.append([100231, dt.datetime(2024, 1, 3), 6.8, 0.9, "H. Fuchs"])
    labor.append([100232, dt.datetime(2024, 1, 6), 7.4, 1.1, "H. Fuchs"])

    visiten = wb.create_sheet("Visiten")
    visiten.append(["Patientenname", "Visitendatum", "Arzt", "Notiz"])
    visiten.append(["Lisa Braun", dt.datetime(2024, 2, 1), "Dr. Vogel", "stabil"])
    visiten.append(["Müller, Max", dt.datetime(2024, 2, 2), "Dr. Fuchs", "Welcher Herr Müller? Bitte klären"])

    hidden = wb.create_sheet("Intern")
    hidden.append(["Vorname", "Nachname", "Telefon"])
    hidden.append(["Sabine", "Müller", "0421 5550123"])
    hidden.sheet_state = "hidden"
    wb.save(root / LABOR)

    # --- SPSS: value labels with doctors, separate name columns ----------------------------
    df = pd.DataFrame(
        {
            "vpn": [100237.0, 100238.0, 100240.0],
            "vorname": ["Erika", "Ayşe", "Friedrich"],
            "nachname": ["Mustermann-Kaya", "Öztürk", "von der Heide"],
            "gebdat": pd.to_datetime(["1951-04-03", "1977-09-22", "1939-11-11"]),
            "behandler": [1.0, 2.0, 2.0],
            "zufrieden": [4.0, 99.0, 2.0],
            "kommentar": ["Morbus Parkinson", "Frau Öztürk spricht gut Deutsch", ""],
        }
    )
    pyreadstat.write_sav(
        df,
        str(root / SAV),
        file_label="Fragebogen DIAB-2, Erhebung Prof. Dr. Bernd Hahn",
        column_labels=["Versuchsperson", "Vorname", "Nachname", "Geburtsdatum", "Behandelnder Arzt",
                       "Zufriedenheit", "Kommentar"],
        variable_value_labels={"behandler": {1.0: "Dr. Weiß", 2.0: "Prof. Hahn"},
                               "zufrieden": {1.0: "gar nicht", 4.0: "sehr", 99.0: "keine Angabe"}},
        missing_ranges={"zufrieden": [99.0]},
    )

    # --- Word letter: which Max Müller? ------------------------------------------------------
    doc = Document()
    doc.sections[0].header.paragraphs[0].text = "Klinikum Nordstadt, Klinik für Innere Medizin, Direktor: Prof. Dr. med. Bernd Hahn"
    doc.sections[0].footer.paragraphs[0].text = "Sekretariat: Tel. 0421 555-0100, innere@klinikum-nordstadt.example"
    for text in [
        "Frau Dr. med. Hannelore Fuchs\nGartenstraße 12\n28203 Bremen",
        "Bremen, den 20.01.2024",
        "Arztbrief",
        "Sehr geehrte Frau Kollegin Fuchs,",
        "wir berichten über Ihren Patienten Herrn Max Müller, geb. am 03.11.1962, wohnhaft Am Deich 17a, "
        "28199 Bremen, der sich vom 05.01.2024 bis zum 12.01.2024 in unserer stationären Behandlung befand.",
        "Diagnosen: Herzinsuffizienz NYHA II (I50.1), arterielle Hypertonie, Diabetes mellitus Typ 2.",
        "Herr Müller stellte sich mit Dyspnoe vor. Der 61-jährige Patient berichtete, seine Frau habe ihn gebracht. "
        "Blutdruck 130/80 mmHg, HbA1c 7,4 %, pH 7,40, Glasgow Coma Scale 15, Barthel-Index 85.",
        "Medikation bei Entlassung: Ramipril 5 mg 1-0-1, Metformin 1000 mg 1-0-1, Insulin glargin 10-0-10 IE.",
        "Herr Müllers Ehefrau wurde über den Verlauf informiert. Lange Zeit war er beschwerdefrei.",
        "Mit freundlichen kollegialen Grüßen",
        "Prof. Dr. med. B. Hahn, Direktor          Dr. Stefan Weiß, Oberarzt",
    ]:
        doc.add_paragraph(text)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Patient"
    table.cell(0, 1).text = "Müller, Max (*03.11.1962)"
    table.cell(1, 0).text = "Fallnummer"
    table.cell(1, 1).text = "F-2024-00871"
    doc.core_properties.author = "Dr. Stefan Weiß"
    doc.core_properties.title = "Arztbrief Max Müller"
    doc.save(root / "Briefe" / "Arztbrief_Mueller_Max_1962.docx")

    # --- Plain letters -----------------------------------------------------------------------
    (root / "Briefe" / "Entlassbrief_Öztürk.txt").write_text(
        "Sehr geehrte Damen und Herren,\n\n"
        "wir entlassen heute Frau Ayşe Öztürk (geb. 22.09.1977) nach Hause. Die Tochter, Elif Öztürk, begleitet sie.\n"
        "Frau Öztürks Morbus Crohn ist unter Therapie stabil. Rücksprache mit dem Hausarzt Dr. Fuchs erfolgte am 14.01.2024.\n"
        "Versichertennummer: H890123457, IBAN für Erstattung: DE02 1203 0000 0000 2020 51.\n"
        "Kontakt: ayse.oeztuerk@mail.example, mobil +49 171 5550166.\n"
        "Wohnhaft: Weserstraße 55, 28199 Bremen. Geboren in Izmir.\n",
        encoding="utf-8",
    )
    (root / "Briefe" / "Kurznotizen.md").write_text(
        "# Stationsnotizen 3B\n\n"
        "- 05.01. Fr. Braun (die aus 09.10.80) klagt ueber Kopfschmerz\n"
        "- Pat. Schulz, P. wieder eingetroffen, Sohn Daniel informiert\n"
        "- Hr. Lange: Blutzucker 180, Dr. Vogel verstaendigt\n"
        "- Frau Schwarz (Zi. 12) schwarzer Stuhlgang, Kontrolle morgen\n"
        "- Herr von der Heide verwirrt, Betreuerin Fr. Kowalczyk angerufen\n"
        "- Frau Mai: Termin im Mai verschoben. Kleine Wunde am Arm.\n"
        "- Patientin Nguyen Thi Lan, Morbus Basedow, stabil\n"
        "- Familie Weber hat angerufen wegen Herrn Weber\n",
        encoding="utf-8",
    )
    (root / "Briefe" / "Mail_an_Hausarzt.txt").write_text(
        "Von: Stefan Weiss <s.weiss@klinikum-nordstadt.example>\n"
        "An: Hannelore Fuchs <praxis.fuchs@mail.example>\n"
        "Betreff: Maria Klein, geb. 02.02.1960\n\n"
        "Liebe Hannelore,\n\n"
        "anbei der Befund von Maria Klein. Die Struma ist klein und unauffaellig.\n"
        "Bitte Kontrolle im Mai. Hashimoto bleibt die Hauptdiagnose.\n\n"
        "Viele Gruesse\nStefan\n",
        encoding="utf-8",
    )

    # --- Folder and file names with names and birth dates ------------------------------------
    (root / "Patienten" / "Schulz_Peter_12031948" / "Befund.txt").write_text(
        "Befund vom 12.02.2024\nPatient: Schulz, Peter (*12.3.1948)\nDiagnose: COPD GOLD II\n", encoding="utf-8"
    )

    # --- Analysis script with values written in the code --------------------------------------
    (root / "Analyse" / "auswertung.R").write_text(
        "# Auswertung DIAB-2, Autorin: Dr. Ingrid Vogel\n"
        'daten <- read.csv2("daten/KIS_Export_2024.csv")\n'
        'ausschluss <- c("Max Müller", "Erika Mustermann-Kaya")\n'
        'teil <- subset(daten, Patient != "Klein, Maria")\n'
        "summary(lm(HbA1c ~ Gruppe + Alter, data = teil))\n",
        encoding="utf-8",
    )
    (root / "Analyse" / "studie.json").write_text(
        '{"pi": "Prof. Dr. Bernd Hahn", "kontakt": "b.hahn@klinikum-nordstadt.example",\n'
        ' "patienten": [{"name": "Renate Schwarz", "geb": "1944-01-20", "gruppe": "Kontrolle"}]}\n',
        encoding="utf-8",
    )

    # --- PDF with a line break inside a name --------------------------------------------------
    pdf = canvas.Canvas(str(root / "Entlassung_Lange.pdf"), pagesize=A4)
    y = 800
    for line in [
        "Entlassungsbericht",
        "Wir berichten über den stationären Aufenthalt von Herrn Wolfgang",
        "Lange, geboren am 19.12.1950, wohnhaft Bahnhofstraße 2, 28195 Bremen.",
        "Herr Lange wurde mit Parkinson-Syndrom aufgenommen. Lange Zeit ging es ihm gut.",
    ]:
        pdf.drawString(50, y, line)
        y -= 18
    pdf.save()
    return root


# =========================================================================== answer key
# Values that must not appear anywhere in the output, including file names and metadata.
MUST_GO = {
    "patient names": [
        "Müller", "Mueller", "Braun, Lisa", "Lisa Braun", "Meier", "Hans-Jürgen", "Hans Jürgen", "Mustermann-Kaya",
        "Erika", "Öztürk", "Ayşe", "Nguyen", "Thi Lan", "von der Heide", "Friedrich", "Maria Klein", "Klein, Maria",
        "Stefan Weiß", "Weiß, Stefan", "Mai, Jana", "Frau Mai", "Kowalczyk", "Zofia", "Schulz", "Peter",
        "Wolfgang", "Herr Lange", "Hr. Lange", "Renate", "Frau Schwarz",
    ],
    "relatives and contacts": ["Sabine", "Sohn Tim", "Elif", "Daniel", "Şahin", "Weber"],
    "doctors": ["Hannelore", "Fuchs", "Ingrid", "Vogel", "Hahn", "Dr. Weiß", "Stefan Weiss", "Oberarzt Dr. Weiß"],
    "birth dates": [
        "12.05.1975", "03.11.1962", "01.03.1980", "09.10.1980", "09.10.80", "14.02.1941", "30.06.1968", "03.04.1951",
        "22.09.1977", "07.07.1985", "11.11.1939", "02.02.1960", "05.05.1955", "15.08.1992", "19.12.1950", "12.3.1948",
        "12031948", "20.01.1944", "1944-01-20", "1962-11-03", "1975-05-12",
    ],
    "IDs": [
        "100231", "100232", "100235", "100236", "100237", "100244", "A123456780", "H890123457", "F-2024-00871",
    ],
    "contact details": [
        "0421/5550123", "0171-5550144", "+49 171 5550166", "0421 555-0100", "ayse.oeztuerk", "s.weiss@", "praxis.fuchs",
        "b.hahn@", "DE02 1203",
    ],
    "addresses": [
        "Lindenallee", "Am Deich", "Hauptstr. 9", "Birkenweg", "Kaiserstraße", "Weserstr", "Ostertorsteinweg",
        "Am Wall", "Rosenweg", "Marktplatz", "Mozartstr", "Gartenstraße", "Bahnhofstraße", "28195", "28199", "27749",
        "Delmenhorst",
    ],
}

# Words that must survive, because the research depends on them.
MUST_STAY = {
    "diseases named after people": [
        "Morbus Parkinson", "Morbus Crohn", "Morbus Basedow", "Morbus Alzheimer", "Hashimoto", "Parkinson-Syndrom",
    ],
    "scores and clinical terms": [
        "Glasgow Coma Scale", "Barthel-Index", "NYHA II", "COPD GOLD II", "Herzinsuffizienz", "Diabetes mellitus",
        "Dyspnoe", "HbA1c",
    ],
    "doses and measurements": [
        "Ramipril 5 mg 1-0-1", "Metformin 1000 mg 1-0-1", "10-0-10 IE", "130/80 mmHg", "7,4 %", "7,40",
    ],
    "diagnosis codes": ["I50.1", "E11.9", "G20.1", "K50.0", "G30.1"],
    "column headers": [
        "Pat.-Nr.", "Geb.-Datum", "Versichertennr.", "Diagnose (ICD)", "Station", "Hausarzt", "Bemerkung", "Patientenname",
        "Visitendatum", "Kreatinin", "Unterschrift", "Geburtsdatum",
    ],
    "group labels and words that are also names": [
        "Intervention", "Kontrolle", "Struma klein", "ist klein", "schwarzer Stuhlgang", "Lange Zeit", "Kleine Wunde",
        "Termin im Mai", "Kontrolle im Mai", "Sehr geehrte", "Mit freundlichen", "Patient", "Diagnosen",
    ],
    "analysis code": ['read.csv2("daten/', "summary(lm(HbA1c ~ Gruppe + Alter, data = teil))"],
}

# Who is really who, per row of the tables: file, sheet (or None), row (0 = first data row) -> person.
KIS_PEOPLE = ["max75", "max62", "lisa_mar", "lisa_okt", "hj41", "hj68", "erika", "ayse", "lan", "friedrich",
              "maria", "stefan_pat", "jana"]
STAMM_PEOPLE = ["max75", "max62", "hj41", "hj68", "zofia"]
SAV_PEOPLE = ["erika", "ayse", "friedrich"]
BASE = re.compile(r"PERSON_\d{4,}")


# =========================================================================== reading results
def all_text(folder: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(folder.rglob("*")):
        rel = str(path.relative_to(folder))
        found[f"{rel} [path]"] = rel
        if not path.is_file():
            continue
        if path.suffix in (".docx", ".xlsx"):
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():
                    if name.endswith((".xml", ".rels")):
                        raw = z.read(name).decode("utf-8", "replace")
                        found[f"{rel} [{name}]"] = re.sub(r"<[^>]+>", "", raw).replace("&amp;", "&")
        elif path.suffix == ".sav":
            df, meta = pyreadstat.read_sav(str(path), user_missing=True)
            found[f"{rel} [data]"] = df.to_csv()
            found[f"{rel} [labels]"] = (
                f"{meta.column_names_to_labels} {meta.variable_value_labels} {meta.file_label} {meta.notes}"
            )
        else:
            found[rel] = path.read_bytes().decode("utf-8-sig", "replace")
    return found


def _first_code(value) -> str | None:
    m = BASE.search(str(value))
    return m.group(0) if m else None


def identity_problems(out: Path) -> tuple[list[str], list[str]]:
    """Returns (merged different people, split one person), as readable lines."""
    seen: list[tuple[str, str, str]] = []  # person, code, where

    text = next(out.glob("daten/*.csv")).read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    at = next(i for i, r in enumerate(rows) if len(r) > 2 and r[2] == "Geb.-Datum")
    for person, row in zip(KIS_PEOPLE, rows[at + 1 :]):
        seen.append((person, _first_code(row[1]) or f"(no code: {row[1]})", "KIS"))

    wb = load_workbook(next(out.glob("daten/*.xlsx")))
    ws = wb.worksheets[0]
    for person, r in zip(STAMM_PEOPLE, range(4, 9)):
        seen.append((person, _first_code(ws.cell(r, 2).value) or f"(no code: {ws.cell(r, 2).value})", "Excel"))

    df, _ = pyreadstat.read_sav(str(next(out.glob("daten/*.sav"))))
    for person, value in zip(SAV_PEOPLE, df["nachname"]):
        seen.append((person, _first_code(value) or f"(no code: {value})", "SPSS"))

    by_person: dict[str, set[str]] = {}
    by_code: dict[str, set[str]] = {}
    for person, code, _ in seen:
        by_person.setdefault(person, set()).add(code)
        by_code.setdefault(code, set()).add(person)
    merged = [f"{code} = {sorted(people)}" for code, people in by_code.items() if len(people) > 1]
    split = [f"{person}: {sorted(codes)}" for person, codes in by_person.items() if len(codes) > 1]
    return merged, split


def mention_checks(out: Path, texts: dict[str, str]) -> list[tuple[bool, str]]:
    rows = list(csv.reader(io.StringIO(next(out.glob("daten/*.csv")).read_text(encoding="utf-8-sig")), delimiter=";"))
    at = next(i for i, r in enumerate(rows) if len(r) > 2 and r[2] == "Geb.-Datum")
    code = {p: _first_code(r[1]) for p, r in zip(KIS_PEOPLE, rows[at + 1 :])}
    letter = next(v for k, v in texts.items() if "word/document.xml" in k)
    results = [
        (f"Herrn {code['max62']}," in letter or f"Patienten Herrn {code['max62']}" in letter,
         "Letter links 'Herrn Max Müller, geb. 03.11.1962' to the right Max"),
        (code["max75"] not in letter, "Letter never uses the other Max Müller's code"),
        (f"{code['max62']}_" in letter, "'Herr Müller' in the letter links to that Max (surname code)"),
    ]
    note = next((v for k, v in texts.items() if k.endswith("Entlassbrief") or "Entlassbrief" in k and "[path]" not in k), "")
    results.append((code["ayse"] in note, "Discharge letter links Frau Ayşe Öztürk by birth date"))
    return results


def round_trip(work: Path, source: Path, out: Path) -> list[str]:
    results = work / "Ergebnisse"
    shutil.copytree(out, results)
    restore_folder(results, work / f"{source.name}_privatier" / KEY_FILE, PASSWORD)
    restored = work / "Ergebnisse_restored"
    problems = []
    for original in sorted(source.rglob("*")):
        if original.suffix not in (".txt", ".md", ".R", ".json"):
            continue
        rel = original.relative_to(source)
        target = restored / rel
        if not target.exists():
            problems.append(f"{rel}: file name not restored")
        elif target.read_bytes() != original.read_bytes():
            before = original.read_text(encoding="utf-8").splitlines()
            after = target.read_text(encoding="utf-8").splitlines()
            bad = [(a, b) for a, b in zip(before, after) if a != b]
            problems.append(f"{rel}: {len(bad)} line(s) differ, e.g. {bad[:1]}")
    return problems


def run(use_ai: bool, keep: Path | None = None) -> dict:
    work = Path(tempfile.mkdtemp(prefix="hard_"))
    source = make(work / "Studie")
    summary = anonymize_folder(source, PASSWORD, use_ai=use_ai)
    out = work / "Studie_anonymized"
    texts = all_text(out)

    leaks = {
        group: {v: sorted({k.split(" [")[0] for k, t in texts.items() if v in t}) for v in values
                if any(v in t for t in texts.values())}
        for group, values in MUST_GO.items()
    }
    damaged = {
        group: [v for v in values if not any(v in t for t in texts.values())] for group, values in MUST_STAY.items()
    }
    merged, split = identity_problems(out)
    report = {
        "leaks": leaks,
        "damaged": damaged,
        "merged": merged,
        "split": split,
        "mentions": mention_checks(out, texts),
        "round_trip": round_trip(work, source, out),
        "errors": summary.errors,
        "warnings": summary.warnings,
        "people": load_vault(work / "Studie_privatier" / KEY_FILE, PASSWORD)["people"],
    }
    if keep:
        shutil.rmtree(keep, ignore_errors=True)
        shutil.copytree(out, keep)
    shutil.rmtree(work)
    return report


def show(report: dict) -> int:
    failures = 0
    for title, key in (("LEAKS (must be gone, still there)", "leaks"), ("DAMAGE (must stay, was replaced)", "damaged")):
        total = sum(len(v) for v in report[key].values())
        failures += total
        print(f"\n{title}: {total}")
        for group, items in report[key].items():
            if items:
                print(f"  {group}: " + (", ".join(items) if isinstance(items, list) else ""))
                if isinstance(items, dict):
                    for value, files in items.items():
                        print(f"    {value!r}: {', '.join(files)}")
    print(f"\nMERGED different people: {len(report['merged'])}")
    for line in report["merged"]:
        print("  " + line)
    print(f"SPLIT one person: {len(report['split'])}")
    for line in report["split"]:
        print("  " + line)
    failures += len(report["merged"]) + len(report["split"])
    print("\nLINKS IN LETTERS")
    for ok, label in report["mentions"]:
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")
        failures += not ok
    print(f"\nRESTORE differences: {len(report['round_trip'])}")
    for line in report["round_trip"]:
        print("  " + line)
    failures += len(report["round_trip"])
    print(f"\nFILE ERRORS: {report['errors']}")
    failures += len(report["errors"])
    print(f"\nPLEASE-CHECK LIST: {len(report['warnings'])} notes")
    for file, note in report["warnings"]:
        print(f"  {file}: {note}")
    print(f"\nTOTAL PROBLEMS: {failures}")
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ai", action="store_true", help="also use the local AI model")
    parser.add_argument("--keep", type=Path, help="copy the anonymised output to this folder for reading")
    args = parser.parse_args()
    sys.exit(1 if show(run(args.ai, args.keep)) else 0)
