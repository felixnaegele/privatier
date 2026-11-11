"""Third hard test, a psychology study with interviews. All invented. Usage: python tools/hard_data_3.py [--ai]"""
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

use_ai = "--ai" in sys.argv
work = Path(tempfile.mkdtemp(prefix="third_"))
src = work / "Psych_Studie"
src.mkdir()
(src / "interviews").mkdir()

(src / "register.csv").write_bytes(
    (
        "lfd. Nr.;Titel;Name;Vorname;geb.;Alter;Wohnort;Therapeut;Einschluss;Bemerkungen\n"
        "1;;Hoffmann;Karin;23.08.1961;62;Kiel;Dr. Pohl;01.02.2023;Karin ist Lehrerin an der Gorch-Fock-Schule\n"
        "2;Dr.;Hoffmann;Karin;14.12.1984;39;Lübeck;Dr. Pohl;08.02.2023;Keine Verwandtschaft zu Nr. 1\n"
        "3;;Petersen;Ole;02.06.1999;24;Kiel;Dipl.-Psych. Marta Nowak;15.02.2023;Ole P. hat abgebrochen\n"
        "4;;Jansen;Fenja;;31;Flensburg;Dipl.-Psych. Marta Nowak;22.02.2023;Geburtsdatum fehlt\n"
        "5;Prof.;van den Berg;Willem;30.04.1955;68;Husum;Dr. Pohl;01.03.2023;Ehefrau Annelies begleitet ihn\n"
        "6;;Rahimi;Mohammad Reza;17.09.1990;33;Kiel;Dr. Pohl;08.03.2023;Herr Rahimi benötigt Dolmetscher\n"
    ).encode("cp1252", "replace")
)

wb = Workbook()
ws = wb.active
ws.title = "Scores"
ws.append(["Code", "Nachname", "Vorname", "Geburtsjahr", "BDI-II", "HAMD", "Kommentar"])
ws.append(["K01", "Hoffmann", "Karin", 1961, 21, 14, "Frau Hoffmann schläft schlecht"])
ws.append(["K02", "Hoffmann", "Karin", 1984, 9, 5, "unauffällig"])
ws.append(["O03", "Petersen", "Ole", 1999, 30, 22, "Suizidgedanken, Vater Lars informiert"])
ws.append(["F04", "Jansen", "Fenja", None, 12, 8, ""])
wb.save(src / "scores.xlsx")

(src / "interviews" / "Interview_K01.txt").write_text(
    "Interview mit Karin Hoffmann (Jg. 1961) am 3. Februar 2023 in Kiel\n"
    "I: Wie geht es Ihnen, Frau Hoffmann?\n"
    "B: Seit mein Mann Jens gestorben ist, kaum besser. Meine Schwester Birgit in Rostock hilft mir.\n"
    "B: Dr. Pohl sagt, das ist normal. Ich arbeite noch bei Edeka in der Holstenstraße.\n"
    "I: Wer war noch dabei?\n"
    "B: Meine Nachbarin, die Frau Clausen, und mein Enkel Finn.\n"
    "Beck-Depressions-Inventar: 21 Punkte. Freud'sche Deutung nicht relevant. Nach ICD-10 F32.1.\n",
    encoding="utf-8",
)
(src / "interviews" / "Protokoll Rahimi.txt").write_text(
    "Protokoll der Sitzung vom 08.03.2023\n"
    "Teilnehmer: M. R. Rahimi, Dolmetscherin Leyla Haddad\n"
    "Klient lebt seit 2015 in Deutschland, stammt aus Mashhad. Seine Frau heißt Zahra.\n"
    "Rückfragen: leyla.haddad@dolmetscher.example oder 0431 5550142.\n"
    "Sozialversicherungsnr. 12 170990 R 123, Personalausweis L01X00T47.\n",
    encoding="utf-8",
)
doc = Document()
doc.add_paragraph("Gutachten über Herrn Prof. Willem van den Berg, geb. 30.04.1955")
doc.add_paragraph("Herr van den Berg wurde von Frau Dipl.-Psych. Nowak untersucht. Prof. van den Berg war kooperativ.")
doc.add_paragraph("Der Mini-Mental-Status-Test ergab 27 Punkte. Der Clock-Drawing-Test war unauffällig.")
doc.save(src / "Gutachten_vdBerg.docx")

summary = anonymize_folder(src, "third password", use_ai=use_ai)
out = work / "Psych_Studie_pseudonymised"

texts = {}
for p in out.rglob("*"):
    rel = str(p.relative_to(out))
    if p.suffix == ".xlsx":
        texts[rel] = "\n".join(" | ".join("" if v is None else str(v) for v in r) for r in load_workbook(p).active.iter_rows(values_only=True))
    elif p.suffix == ".docx":
        texts[rel] = "\n".join(x.text for x in Document(p).paragraphs)
    elif p.is_file():
        texts[rel] = p.read_bytes().decode("cp1252", "replace") if p.suffix == ".csv" else p.read_text(encoding="utf-8")

MUST_GO = ["Hoffmann", "Karin", "Petersen", "Ole", "Jansen", "Fenja", "van den Berg", "Willem", "Rahimi", "Mohammad",
           "Pohl", "Nowak", "Marta", "Annelies", "Lars", "Jens", "Birgit", "Clausen", "Finn", "Haddad", "Leyla", "Zahra",
           "23.08.1961", "14.12.1984", "02.06.1999", "30.04.1955", "17.09.1990", "leyla.haddad", "0431 5550142",
           "12 170990", "L01X00T47", "Holstenstraße", "Rostock", "Lübeck", "Husum", "Flensburg", "Mashhad", "Gorch-Fock"]
SOFT = ["Kiel", "Edeka", "K01", "O03"]
MUST_STAY = ["Beck-Depressions-Inventar", "Freud'sche", "ICD-10 F32.1", "Mini-Mental-Status-Test", "Clock-Drawing-Test",
             "BDI-II", "HAMD", "Geburtsjahr", "Therapeut", "Einschluss", "Bemerkungen", "lfd. Nr.", "Alter", "Wohnort",
             "Lehrerin", "Dolmetscher", "Suizidgedanken", "unauffällig", "Keine Verwandtschaft", "Geburtsdatum fehlt",
             "schläft schlecht", "Protokoll der Sitzung", "Gutachten"]

print("MODE:", "AI" if use_ai else "rules only")
leaks = {v: sorted({k.split(" [")[0] for k, t in texts.items() if v in t}) for v in MUST_GO if any(v in t for t in texts.values())}
print(f"LEAKS {len(leaks)}/{len(MUST_GO)}")
for v, f in leaks.items():
    print("  ", repr(v), f)
print("  also present (arguable):", [v for v in SOFT if any(v in t for t in texts.values())])
gone = [v for v in MUST_STAY if not any(v in t for t in texts.values())]
print(f"DAMAGE {len(gone)}/{len(MUST_STAY)}:", gone)

rows = list(csv.reader(io.StringIO(next(out.glob("*.csv")).read_bytes().decode("cp1252", "replace")), delimiter=";"))
print("REGISTER")
for r in rows:
    print("  ", r)
print("SCORES")
for r in load_workbook(next(out.glob("*.xlsx"))).active.iter_rows(values_only=True):
    print("  ", r)
for k, t in texts.items():
    if not k.endswith("[path]") and not k.endswith((".csv", ".xlsx")):
        print("---", k)
        print(t)
print("errors:", summary.errors)
for f, w in summary.warnings:
    if "looks like it holds dates" not in w:
        print("  check:", f, "|", w)
shutil.rmtree(work)
