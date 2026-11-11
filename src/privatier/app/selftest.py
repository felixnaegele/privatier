"""Self-test of the installed app: `Privatier --self-test` (no window opens).

It checks, with made-up data in a temporary folder, that everything the app needs is really inside the bundle:
all file readers, the local AI model, anonymising and restoring. One line per check, then SELF-TEST PASSED or FAILED.
"""

from __future__ import annotations

import importlib
import io
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

PASSWORD = "self-test password"

# Made-up people. The last two appear only in running text, with no title or label around them: only the AI finds those.
TABLE_NAMES = ["Heidrun Kowalczyk", "Bertram Oyelaran", "Margaret Thistlewood", "Cornelius Blackwood"]
AI_ONLY_NAMES = ["Wilhelmina Quarkbach", "Fitzgerald Montgomery"]
ALL_NAMES = TABLE_NAMES + AI_ONLY_NAMES

_MODULES = [
    "pandas", "openpyxl", "pyreadstat", "docx", "pypdf", "cryptography", "numpy",
    "gliner", "torch", "transformers", "tokenizers", "sentencepiece", "webview",
    "privatier.engine", "privatier.handlers.csv_handler", "privatier.handlers.excel_handler",
    "privatier.handlers.spss_handler", "privatier.handlers.docx_handler", "privatier.handlers.pdf_handler",
    "privatier.handlers.text_handler", "privatier.app.service", "privatier.app.window",
]


class _Report:
    def __init__(self) -> None:
        self.failed = False

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        print(f"[{'ok' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail and not ok else ""), flush=True)
        self.failed |= not ok
        return ok


def _make_data(folder: Path) -> None:
    import pandas as pd
    import pyreadstat
    from docx import Document

    folder.mkdir(parents=True)
    table = pd.DataFrame(
        {
            "Patient": TABLE_NAMES,
            "Geburtsdatum": ["1961-03-14", "1975-11-02", "1948-07-30", "1990-01-25"],
            "Diagnose": ["Typ-2-Diabetes", "Asthma", "Hypertonie", "Migraene"],
            "Wert": [7.4, 5.1, 6.2, 5.9],
        }
    )
    table.to_excel(folder / "Studie.xlsx", index=False)
    table.to_csv(folder / "Daten.csv", index=False, sep=";")
    pyreadstat.write_sav(table, str(folder / "Daten.sav"))
    doc = Document()
    doc.add_paragraph(f"Patient: {TABLE_NAMES[0]}, geboren am 14.03.1961. Verlauf unauffaellig.")
    doc.add_paragraph(f"Patient: {TABLE_NAMES[2]}, born 30 July 1948. No complaints at the follow-up.")
    doc.save(str(folder / "Brief.docx"))
    (folder / "Notiz.txt").write_text(
        f"Gestern ging {AI_ONLY_NAMES[0]} nach dem langen Gespraech zufrieden nach Hause.\n"
        f"Afterwards the team met with {AI_ONLY_NAMES[1]} to talk about the schedule.\n",
        encoding="utf-8",
    )


def _read_all_text(folder: Path) -> str:
    """Everything readable in the folder, as one text."""
    import pyreadstat
    from docx import Document
    from openpyxl import load_workbook

    chunks: list[str] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        chunks.append(path.name)
        suffix = path.suffix.lower()
        if suffix == ".xlsx":
            wb = load_workbook(path)
            for ws in wb.worksheets:
                chunks.extend(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
        elif suffix == ".sav":
            frame, meta = pyreadstat.read_sav(str(path))
            chunks.append(frame.to_csv())
        elif suffix == ".docx":
            document = Document(str(path))
            chunks.extend(p.text for p in document.paragraphs)
        else:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def _present(text: str, names: list[str]) -> list[str]:
    # Surnames count too: "Kowalczyk" alone would be a leak as well.
    return [n for n in names if n in text or n.split()[-1] in text]


def run() -> int:
    report = _Report()
    work: Path | None = None
    try:
        for name in _MODULES:
            try:
                importlib.import_module(name)
                report.check(f"import {name}", True)
            except Exception as exc:
                report.check(f"import {name}", False, f"{type(exc).__name__}: {exc}")

        from pypdf import PdfWriter

        buffer = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(buffer)
        report.check("pdf library writes a page", buffer.tell() > 100)

        from privatier.app import window

        report.check("window page ui.html is inside the app", (Path(window.__file__).parent / "ui.html").is_file())
        if sys.platform == "darwin":
            try:
                importlib.import_module("webview.platforms.cocoa")  # the Mac window code (opens nothing)
                report.check("native Mac window library loads", True)
            except Exception as exc:
                report.check("native Mac window library loads", False, f"{type(exc).__name__}: {exc}")

        from privatier.detect import gliner_detector

        report.check("AI model files are present (model_ready)", gliner_detector.model_ready())
        if sys.platform == "darwin" and getattr(sys, "frozen", False):
            hub = gliner_detector.bundled_hub()
            report.check("AI model is read from inside the app", hub is not None and hub.is_dir(), str(hub))

        work = Path(tempfile.mkdtemp(prefix="privatier-selftest-"))
        source = work / "Selftest"
        _make_data(source)
        report.check("mock data built (xlsx, csv, sav, docx, txt)", len(list(source.iterdir())) == 5)

        from privatier.engine import KEY_FILE, anonymize_folder, restore_folder, scan_folder

        scan = scan_folder(source, use_ai=True)
        report.check("scan with the AI", scan.used_ai and len(scan.tables) >= 3, f"used_ai={scan.used_ai}")

        output = work / "Selftest_out"
        keydir = work / "Selftest_key"
        summary = anonymize_folder(source, PASSWORD, output_dir=output, work_dir=keydir, use_ai=True, level=1)
        report.check(
            "anonymise at level 1 with the AI: all 5 files written",
            len(summary.processed) == 5 and not summary.errors,
            f"processed={summary.processed} errors={[e[0] for e in summary.errors]}",
        )
        out_text = _read_all_text(output)
        report.check("made-up names are gone from the output", not _present(out_text, TABLE_NAMES), str(_present(out_text, TABLE_NAMES)))
        report.check(
            "AI-only names in free text were caught",
            not _present(out_text, AI_ONLY_NAMES),
            "still there: " + ", ".join(_present(out_text, AI_ONLY_NAMES)),
        )
        report.check("non-identifying cells unchanged", "Typ-2-Diabetes" in out_text and "Hypertonie" in out_text)

        restored = work / "Selftest_back"
        restore_folder(output, keydir / KEY_FILE, PASSWORD, restored)
        back_text = _read_all_text(restored)
        missing = [n for n in ALL_NAMES if n not in back_text]
        report.check("restore brings the names back", not missing, "missing: " + ", ".join(missing))
    except Exception:
        traceback.print_exc()
        report.check("self-test ran without an unexpected error", False, "see the error above")
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)
    print("SELF-TEST FAILED" if report.failed else "SELF-TEST PASSED", flush=True)
    return 1 if report.failed else 0
