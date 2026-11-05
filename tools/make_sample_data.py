"""Create a folder of FAKE patient data for testing Privatier.

All names, dates and numbers here are invented. Never test with real data.

    python tools/make_sample_data.py sample_project
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pyreadstat
from docx import Document
from docx.shared import Pt
from openpyxl import Workbook
from openpyxl.comments import Comment

# Every value below must be gone from the anonymised output.
SENSITIVE = [
    "Max", "Müller", "Anna", "Schmidt", "Jürgen", "Weiß", "Sarah", "Johnson",
    "Klaus-Peter", "Becker", "Lena", "Hoffmann", "Brian", "O'Neill", "Petra", "Wagner",
    "max.mueller@example.de", "sarah.j@example.com", "030 1234567", "+49 89 98765432",
    "(617) 555-0199", "A123456789", "DE89 3704 0044 0532 0130 00",
    "Lindenstraße 12", "742 Evergreen Terrace", "12.05.1975", "1975-05-12",
    "PAT-0042", "PAT-0043", "12345678", "Fallnummer 998877",
]


def make(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "daten").mkdir(exist_ok=True)

    # --- CSV, German Excel style: semicolons, Windows encoding ----------------
    csv_text = (
        "Patienten-ID;Vorname;Nachname;Geburtsdatum;Geschlecht;Gruppe;HbA1c;Telefon;Bemerkung\n"
        "PAT-0042;Max;Müller;12.05.1975;m;Intervention;6,8;030 1234567;Rückruf durch Frau Dr. Lena Hoffmann\n"
        "PAT-0043;Petra;Wagner;03.11.1962;w;Kontrolle;7,4;+49 89 98765432;KVNR A123456789, IBAN DE89 3704 0044 0532 0130 00\n"
        "PAT-0044;Jürgen;Weiß;21.01.1958;m;Intervention;8,1;;Termin am 14. März 2023 verschoben\n"
    )
    (root / "daten" / "studie_rohdaten.csv").write_bytes(csv_text.encode("cp1252"))

    # --- Excel: title row above the header, real dates, a comment -------------
    wb = Workbook()
    ws = wb.active
    ws.title = "Patients"
    ws.append(["Study XY - raw data (export 2024)"])
    ws.append(["Patient ID", "First name", "Last name", "Date of birth", "Group", "Outcome", "Email", "Notes"])
    ws.append(["PAT-0045", "Sarah", "Johnson", dt.datetime(1980, 7, 3), "A", 0.82, "sarah.j@example.com",
               "Mr. Brian O'Neill (brother) called from (617) 555-0199"])
    ws.append(["PAT-0046", "Klaus-Peter", "Becker", dt.datetime(1949, 2, 28), "B", 0.64, None,
               "Lives at 742 Evergreen Terrace"])
    ws["H3"].comment = Comment("Checked by Anna Schmidt", "Anna Schmidt")
    wb.properties.creator = "Anna Schmidt"
    wb.save(root / "daten" / "outcomes.xlsx")

    # --- SPSS ---------------------------------------------------------------
    df = pd.DataFrame(
        {
            "pid": [12345678.0, 12345679.0, 12345680.0],
            "name": ["Max Müller", "Petra Wagner", "Jürgen Weiß"],
            "gebdat": pd.to_datetime(["1975-05-12", "1962-11-03", "1958-01-21"]),
            "gruppe": [1.0, 2.0, 1.0],
            "score": [12.5, 9.0, 14.25],
        }
    )
    pyreadstat.write_sav(
        df,
        str(root / "daten" / "fragebogen.sav"),
        column_labels=["Patientennummer", "Name des Patienten", "Geburtsdatum", "Studiengruppe", "Summenscore"],
        variable_value_labels={"gruppe": {1.0: "Intervention", 2.0: "Kontrolle"}},
    )

    # --- Word letter: name split over several runs, header, footer, table ---
    doc = Document()
    doc.sections[0].header.paragraphs[0].text = "Universitätsklinikum Musterstadt - Fallnummer 998877"
    doc.sections[0].footer.paragraphs[0].text = "Kontakt: max.mueller@example.de"
    doc.add_paragraph("Arztbrief")
    p = doc.add_paragraph("Wir berichten über unsere gemeinsame Patientin ")
    r = p.add_run("Anna ")
    r.bold = True
    r2 = p.add_run("Schmidt")
    r2.bold = True
    r2.font.size = Pt(12)
    p.add_run(", geb. 12.05.1975, wohnhaft Lindenstraße 12, 10115 Berlin.")
    doc.add_paragraph("Frau Schmidt stellte sich mit Thoraxschmerz vor. Rückfragen gerne an Herrn Dr. Jürgen Weiß.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Patient"
    table.cell(0, 1).text = "Anna Schmidt"
    table.cell(1, 0).text = "Hausarzt"
    table.cell(1, 1).text = "Dr. Klaus-Peter Becker"
    doc.core_properties.author = "Max Müller"
    doc.save(root / "Arztbrief_Schmidt.docx")

    # --- PDF -----------------------------------------------------------------
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(root / "discharge_summary.pdf"), pagesize=A4)
    lines = [
        "Discharge summary",
        "Patient: Sarah Johnson, MRN 12345678, born 1975-05-12",
        "Mrs. Johnson was admitted with community-acquired pneumonia.",
        "Contact: sarah.j@example.com, phone (617) 555-0199",
    ]
    y = 800
    for line in lines:
        c.drawString(60, y, line)
        y -= 20
    c.save()

    # --- Something Privatier cannot read (must be skipped, not copied) -------
    (root / "scan_befund.jpg").write_bytes(b"\xff\xd8\xff\xe0 fake image Anna Schmidt")
    (root / ".DS_Store").write_bytes(b"\x00")
    return root


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_project")
    print(f"Fake sample data written to {make(target).resolve()}")
