"""Does an analysis give the same answer after anonymising? Prints verdicts, never values or statistics.

Works on a copy of the folder; the originals are not touched, and everything stays on this computer.

    python tools/compare_stats.py <folder> [--ai]

Each column gets one verdict:
  same         every value identical (and so every statistic)
  spacing only stray spaces around a value are gone, nothing else
  replaced     identifying column: as many different values as before, in the same rows
  year only    birth date: reduced to the year, and the years are correct
  text edited  free text: only the listed number of cells changed
  DIFFERENT    a clinical value changed. This should never happen
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat

from privatier.engine import KEY_FILE, anonymize_folder, restore_folder
from privatier.tables import classify_header

PASSWORD = "comparison run"
_IDENTIFYING = {"PERSON", "ID", "ADDRESS", "EMAIL", "PHONE"}


def _missing(value) -> bool:
    return value is None or value is pd.NaT or (isinstance(value, float) and value != value)


def _same(a, b) -> bool:
    if _missing(a) or _missing(b):
        return _missing(a) and _missing(b)
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    try:
        return bool(a == b) or float(a) == float(b)
    except (TypeError, ValueError):
        return False


def _year_of(value) -> int | None:
    if hasattr(value, "year"):
        return int(value.year)
    text = str(value)
    for piece in text.replace("-", ".").replace("/", ".").split("."):
        if len(piece) == 4 and piece.isdigit():
            return int(piece)
    return None


def judge_column(name: str, before: pd.Series, after: pd.Series, label: str | None = None) -> tuple[str, int]:
    """Verdict and the number of cells that differ."""
    changed = sum(not _same(a, b) for a, b in zip(before, after))
    if len(before) != len(after):
        return "DIFFERENT", abs(len(before) - len(after))
    if changed == 0:
        return "same", 0
    if all(_same(a, b) or (isinstance(a, str) and isinstance(b, str) and a.split() == b.split()) for a, b in zip(before, after)):
        return "spacing only", changed
    category = classify_header(name, label)
    if category == "DOB":
        wrong = sum(
            not _missing(a) and not (_year_of(a) == _year_of(b) or str(b).startswith("DATE_"))
            for a, b in zip(before, after)
        )
        return ("year only", changed) if wrong == 0 else ("DIFFERENT", wrong)
    if category in _IDENTIFYING:
        rows_ok = sum(_missing(a) != _missing(b) for a, b in zip(before, after)) == 0
        pairs = {(" ".join(str(a).split()), str(b)) for a, b in zip(before, after) if not _missing(a)}
        # One value, one code; a person can only get a second code if the data did not settle who it is.
        code_for_two_values = len({b for _, b in pairs}) < len({a for a, _ in pairs})
        return ("replaced", changed) if rows_ok and not code_for_two_values else ("DIFFERENT", changed)
    numeric_before = pd.to_numeric(before, errors="coerce")
    numeric_after = pd.to_numeric(after, errors="coerce")
    numbers_changed = sum(
        not _same(a, b) for a, b, x in zip(numeric_before, numeric_after, before) if not isinstance(x, str)
    )
    all_text = all(isinstance(x, str) or _missing(x) for x, y in zip(before, after) if not _same(x, y))
    return ("text edited", changed) if numbers_changed == 0 and all_text else ("DIFFERENT", changed)


def analysis_is_the_same(before: pd.DataFrame, after: pd.DataFrame, columns: list[str]) -> list[str]:
    """What a statistician would run first, on the columns that should be untouched."""
    problems = []
    a, b = before[columns], after[columns]
    numbers_a = a.apply(pd.to_numeric, errors="coerce")
    numbers_b = b.apply(pd.to_numeric, errors="coerce")
    numeric = [c for c in columns if numbers_a[c].notna().any()]
    if numeric:
        for label, x, y in (
            ("count", numbers_a[numeric].count(), numbers_b[numeric].count()),
            ("mean", numbers_a[numeric].mean(), numbers_b[numeric].mean()),
            ("standard deviation", numbers_a[numeric].std(), numbers_b[numeric].std()),
            ("median", numbers_a[numeric].median(), numbers_b[numeric].median()),
            ("minimum", numbers_a[numeric].min(), numbers_b[numeric].min()),
            ("maximum", numbers_a[numeric].max(), numbers_b[numeric].max()),
        ):
            if not np.array_equal(x.to_numpy(dtype=float), y.to_numpy(dtype=float), equal_nan=True):
                problems.append(label)
        if len(numeric) > 1:
            small = numeric[:150]
            ca, cb = numbers_a[small].corr().to_numpy(), numbers_b[small].corr().to_numpy()
            if not np.array_equal(ca, cb, equal_nan=True):
                problems.append("correlations")
    if a.isna().sum().tolist() != b.isna().sum().tolist():
        problems.append("missing values")
    groups = [c for c in columns if 2 <= a[c].nunique() <= 10]
    for c in groups[:40]:
        if Counter(a[c].dropna().astype(str)) != Counter(b[c].dropna().astype(str)):
            problems.append(f"category counts of {c}")
        if numeric:
            ma = numbers_a[numeric].groupby(a[c].astype(str)).mean().to_numpy()
            mb = numbers_b[numeric].groupby(b[c].astype(str)).mean().to_numpy()
            if ma.shape != mb.shape or not np.array_equal(ma, mb, equal_nan=True):
                problems.append(f"group means by {c}")
    return problems


def compare_table(title: str, before: pd.DataFrame, after: pd.DataFrame, labels: dict | None = None) -> int:
    labels = labels or {}
    print(f"\n{title}: {before.shape[0]} rows, {before.shape[1]} columns")
    failures = 0
    if list(before.columns) != list(after.columns) or before.shape != after.shape:
        print(f"  DIFFERENT layout: {before.shape} -> {after.shape}, same headers: {list(before.columns) == list(after.columns)}")
        return 1
    verdicts = {str(c): judge_column(str(c), before[c], after[c], labels.get(c)) for c in before.columns}
    count = Counter(v for v, _ in verdicts.values())
    print("  columns:", ", ".join(f"{n} {v}" for v, n in sorted(count.items())))
    for name, (verdict, cells) in verdicts.items():
        if verdict == "same":
            continue
        print(f"    {verdict:12} {name[:44]:46} {cells} cell(s)")
        failures += verdict == "DIFFERENT"
    untouched = [c for c in before.columns if verdicts[str(c)][0] == "same"]
    if untouched:
        problems = analysis_is_the_same(before, after, untouched)
        print("  statistics on untouched columns:", "identical" if not problems else f"DIFFERENT: {problems}")
        failures += bool(problems)
    return failures


def _read_excel(path: Path) -> dict[str, pd.DataFrame]:
    return pd.read_excel(path, sheet_name=None, dtype=object, header=0)


def compare_excel(before: Path, after: Path, name: str) -> int:
    a, b = _read_excel(before), _read_excel(after)
    failures = 0
    for (title_a, frame_a), (_, frame_b) in zip(a.items(), b.items()):
        failures += compare_table(f"{name}, sheet {title_a}", frame_a, frame_b)
    if len(a) != len(b):
        failures += 1
        print("  DIFFERENT number of sheets")
    return failures


def compare_spss(before: Path, after: Path, name: str) -> int:
    a, ma = pyreadstat.read_sav(str(before), user_missing=True)
    b, mb = pyreadstat.read_sav(str(after), user_missing=True)
    failures = compare_table(name, a, b, ma.column_names_to_labels)
    identifying = {c for c in a.columns if classify_header(c, ma.column_names_to_labels.get(c))}
    keep = [c for c in a.columns if c not in identifying]
    checks = {
        "variable labels": ma.column_names_to_labels == mb.column_names_to_labels,
        "value labels": {k: v for k, v in ma.variable_value_labels.items() if k in keep}
        == {k: v for k, v in mb.variable_value_labels.items() if k in keep},
        "missing-value definitions": {k: v for k, v in (ma.missing_ranges or {}).items() if k in keep}
        == {k: v for k, v in (mb.missing_ranges or {}).items() if k in keep},
        "measurement levels": {k: ma.variable_measure.get(k) for k in keep} == {k: mb.variable_measure.get(k) for k in keep},
    }
    def _is_text_width(value) -> bool:
        return bool(value) and str(value).startswith("A") and str(value)[1:].isdigit()

    differing = [c for c in keep if ma.original_variable_types.get(c) != mb.original_variable_types.get(c)]
    widths = [c for c in differing if _is_text_width(ma.original_variable_types.get(c)) and _is_text_width(mb.original_variable_types.get(c))]
    formats = [c for c in differing if c not in widths]
    checks["variable formats"] = not formats
    if widths:
        print(f"  text widths follow the longest value for {len(widths)} variable(s), no data is affected")
    for label, ok in checks.items():
        print(f"  {label}: {'identical' if ok else 'DIFFERENT'}")
        failures += not ok
    if formats:
        print(f"    formats differ for {len(formats)} variable(s): {formats[:12]}")
    return failures


def compare_folder(before: Path, after: Path, label: str) -> int:
    failures = 0
    print(f"\n{'=' * 78}\n{label}")
    for path in sorted(before.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(before)
        target = after / relative
        if path.suffix.lower() not in (".xlsx", ".xlsm", ".sav", ".zsav"):
            continue
        if not target.exists():
            print(f"\n{relative}: MISSING from the output")
            failures += 1
            continue
        compare = compare_spss if path.suffix.lower() in (".sav", ".zsav") else compare_excel
        failures += compare(path, target, str(relative))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--ai", action="store_true")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="privatier_compare_"))
    try:
        source = work / "data"
        shutil.copytree(args.folder, source)
        started = dt.datetime.now()
        summary = anonymize_folder(source, PASSWORD, use_ai=args.ai)
        print(f"Anonymised in {(dt.datetime.now() - started).seconds} s, files with errors: {len(summary.errors)}")
        failures = len(summary.errors)
        output = work / "data_anonymized"
        failures += compare_folder(source, output, "ORIGINAL vs ANONYMISED")

        results = work / "results"
        shutil.copytree(output, results)
        restore_folder(results, work / "data_privatier" / KEY_FILE, PASSWORD)
        restored_failures = compare_folder(source, work / "results_restored", "ORIGINAL vs RESTORED")
        print(f"\nTOTAL: anonymising {failures} problem(s), restoring {restored_failures} problem(s)")
        return 1 if failures or restored_failures else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
