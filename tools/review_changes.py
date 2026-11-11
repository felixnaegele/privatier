"""Writes a list of everything in free-text columns, for a person to read. The list holds real text: keep it private.

Sheet "Changed": every edited cell, before and after. Is each change right?
Sheet "Unchanged free text": everything left alone. Is any name still in there?

    python tools/review_changes.py <folder> <list.xlsx> [--ai]
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd
import pyreadstat
from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from privatier.engine import anonymize_folder
from privatier.tables import classify_header


def cells(path: Path) -> dict:
    """(sheet number, sheet, column header, column, row) -> value, for each cell."""
    found = {}
    if path.suffix.lower() in (".sav", ".zsav"):
        frame, _ = pyreadstat.read_sav(str(path), user_missing=True)
        for number, column in enumerate(frame.columns):
            for row, value in enumerate(frame[column], start=2):
                found[(0, "", column, number, row)] = value
    elif path.suffix.lower() in (".csv", ".tsv"):
        frame = pd.read_csv(path, sep=None, engine="python", dtype=str, encoding_errors="replace", on_bad_lines="skip")
        for number, column in enumerate(frame.columns):
            for row, value in enumerate(frame[column], start=2):
                found[(0, "", column, number, row)] = value
    elif path.suffix.lower() in (".xlsx", ".xlsm"):
        for index, ws in enumerate(load_workbook(path).worksheets):
            heads = {c.column: c.value for c in ws[1]}
            for line in ws.iter_rows(min_row=2):
                for cell in line:
                    found[(index, ws.title, heads.get(cell.column), cell.column, cell.row)] = cell.value
    return found


def _clean(value) -> str:
    """Some files hold control characters that Excel cannot store."""
    return ILLEGAL_CHARACTERS_RE.sub("", str(value))


def main() -> None:
    folder, target = Path(sys.argv[1]), Path(sys.argv[2])
    work = Path(tempfile.mkdtemp(prefix="privatier_review_"))
    try:
        source = work / "data"
        shutil.copytree(folder, source)
        anonymize_folder(source, "review run", use_ai="--ai" in sys.argv)
        book = Workbook()
        changed = book.active
        changed.title = "Changed"
        unchanged = book.create_sheet("Unchanged free text")
        heading = ["File", "Sheet", "Column", "Row", "Before", "After"]
        changed.append(heading)
        unchanged.append(heading[:3] + ["Times", "Text"])
        counts = [0, 0]
        for path in sorted(source.rglob("*")):
            output = work / "data_pseudonymised" / path.relative_to(source)
            if not path.is_file() or not output.exists():
                continue
            after = cells(output)
            left_alone: Counter = Counter()
            for key, before in cells(path).items():
                _, sheet, column, _, row = key
                if not isinstance(before, str) or before.startswith("=") or not before.strip():
                    continue
                if classify_header(column if isinstance(column, str) else None):
                    continue  # names and IDs are replaced by design
                new = after.get(key)
                if before != new:
                    changed.append([path.name, sheet, column, row, _clean(before), _clean(new)])
                    counts[0] += 1
                elif any(c.isalpha() for c in before):
                    left_alone[(sheet, str(column), before)] += 1
            for (sheet, column, text), times in sorted(left_alone.items()):
                unchanged.append([path.name, sheet, column, times, _clean(text)])
                counts[1] += 1
        for sheet in (changed, unchanged):
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            sheet.column_dimensions["E"].width = 60
            sheet.column_dimensions["F"].width = 60
        target.parent.mkdir(parents=True, exist_ok=True)
        book.save(target)
        print(f"Changed cells listed: {counts[0]}, unchanged free-text cells listed: {counts[1]}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
