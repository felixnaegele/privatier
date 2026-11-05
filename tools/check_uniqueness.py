"""How many patients can be singled out by what stays in the anonymised copy? Prints counts only.

Someone who knows a patient's age, sex and date of surgery can recognise that patient, even without a name.

    python tools/check_uniqueness.py <folder>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import pyreadstat
from openpyxl import load_workbook

SEX = re.compile(r"(^|_)(sex|gender|geschlecht|geschl)(_|$|\d|=)|sex_", re.IGNORECASE)
AGE = re.compile(r"(^|_)(age|alter)(_|$|\s)|^age", re.IGNORECASE)
BIRTH = re.compile(r"geb\.?\s*_?dat|date\s*_?of\s*_?birth|dateofbirth|^dob$|geburts", re.IGNORECASE)
SURGERY = re.compile(r"date.*surg|surg.*date|^op\s*_?dat|operationsdat|date.*operation", re.IGNORECASE)


def _first(columns, pattern, exclude=None):
    return next((c for c in columns if pattern.search(str(c)) and not (exclude and exclude.search(str(c)))), None)


def tables(folder: Path):
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() in (".xlsx", ".xlsm"):
            for ws in load_workbook(path, data_only=True, read_only=True).worksheets:
                rows = list(ws.iter_rows(values_only=True))
                if len(rows) > 1:
                    yield f"{path.name}, {ws.title}", pd.DataFrame(rows[1:], columns=[str(h) for h in rows[0]])
        elif path.suffix.lower() in (".sav", ".zsav"):
            frame, _ = pyreadstat.read_sav(str(path))
            yield path.name, frame


def report(name: str, frame: pd.DataFrame) -> None:
    frame = frame.loc[:, ~frame.columns.duplicated()]
    birth = _first(frame.columns, BIRTH)
    data = pd.DataFrame(index=frame.index)
    sex, age, surgery = _first(frame.columns, SEX), _first(frame.columns, AGE), _first(frame.columns, SURGERY)
    if sex:
        data["sex"] = frame[sex]
    if age:
        data["age"] = frame[age]
    elif birth:
        data["age"] = pd.to_datetime(frame[birth], errors="coerce", format="mixed").dt.year
    if surgery:
        data["surgery"] = pd.to_datetime(frame[surgery], errors="coerce", format="mixed").dt.date
    data = data.dropna(how="all")
    if len(data) < 5 or data.shape[1] < 2:
        print(f"{name}: not enough such columns to single anyone out")
        return
    print(f"{name}: {len(data)} rows, using {', '.join(data.columns)}")
    combinations = [["sex", "age"], ["surgery"], ["sex", "age", "surgery"]]
    for combination in combinations:
        if all(c in data.columns for c in combination):
            subset = data[combination].dropna()
            sizes = subset.groupby(combination, dropna=True).size()
            unique = int((sizes == 1).sum())
            print(f"   {' + '.join(combination):26} unique: {unique} of {len(subset)} ({100 * unique / max(1, len(subset)):.0f}%)")


if __name__ == "__main__":
    for title, table in tables(Path(sys.argv[1])):
        report(title, table)
