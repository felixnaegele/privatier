"""Stored formula results in Excel files.

An .xlsx file keeps each formula together with its last result. Excel recalculates when a file is
opened, but Python, R and AI tools read the stored result, so without it these cells look empty.
The library that rewrites the file drops these results, so they are read from the original file and
put back into the new one.

A stored result can leak data: =D2 stores a birth date, =A2&" "&B2 a full name. So a result is only
kept if the formula provably does not depend on an identifying column, directly or through other
formulas. If that cannot be told (references to other files, named ranges), it is not kept.
"""

from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path, PurePosixPath

from lxml import etree
from openpyxl.utils import column_index_from_string, coordinate_to_tuple

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PACKAGE_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_TEXT_IN_FORMULA = re.compile(r'"(?:[^"]|"")*"')
_SHEET = r"(?:'((?:[^']|'')+)'|([^\W\d][\w.]*))!"
_REFERENCE = re.compile(
    rf"(?<![\w.])(?:{_SHEET})?(?:"
    r"\$?([A-Z]{1,3})\$?\d+(?::\$?([A-Z]{1,3})\$?\d+)?"  # A1 or A1:C9
    r"|\$?([A-Z]{1,3}):\$?([A-Z]{1,3})"  # A:C
    r"|\$?\d+:\$?\d+"  # 1:5, whole rows
    r")(?![\w(.])"
)
_FUNCTION = re.compile(r"[A-Za-z_][\w.]*\(")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?(?![\w.])")
_CONSTANT = re.compile(r"(?<![\w.])(?:TRUE|FALSE|#N/A|#REF!|#VALUE!|#DIV/0!|#NAME\?|#NUM!|#NULL!)(?![\w.])", re.IGNORECASE)
_LEFTOVER_NAME = re.compile(r"[^\W\d]")

ALL_COLUMNS = -1
_ROUNDING = 1e-14


def references(formula: str) -> list[tuple[str | None, int]] | None:
    """(sheet, column) pairs a formula reads. None if it reads something that cannot be told apart here."""
    text = _TEXT_IN_FORMULA.sub('""', formula.lstrip("="))
    if "[" in text:
        return None  # another workbook, or a structured table reference
    found: list[tuple[str | None, int]] = []

    def note(m: re.Match[str]) -> str:
        sheet = (m.group(1) or m.group(2) or None)
        if sheet:
            sheet = sheet.replace("''", "'")
        first, last = m.group(3) or m.group(5), m.group(4) or m.group(6)
        if first is None:
            found.append((sheet, ALL_COLUMNS))
        else:
            start = column_index_from_string(first)
            stop = column_index_from_string(last) if last else start
            found.extend((sheet, c) for c in range(min(start, stop), max(start, stop) + 1))
        return " "

    rest = _REFERENCE.sub(note, text)
    rest = _FUNCTION.sub(" ", rest)
    rest = _CONSTANT.sub(" ", rest)
    rest = _NUMBER.sub(" ", rest)
    # A word that is left is a named range: it could point anywhere.
    return None if _LEFTOVER_NAME.search(rest.replace('""', " ")) else found


def unsafe_columns(formulas: dict[str, dict[int, list[str]]], sensitive: dict[str, set[int]]) -> dict[str, set[int]]:
    """Columns whose formula results may depend on identifying columns, also through other formulas.

    formulas: sheet -> column -> formula texts. sensitive: sheet -> identifying columns.
    """
    unsafe = {sheet: set(columns) for sheet, columns in sensitive.items()}
    reads = {
        (sheet, column): [references(f) for f in texts]
        for sheet, columns in formulas.items()
        for column, texts in columns.items()
    }
    changed = True
    while changed:
        changed = False
        for (sheet, column), all_references in reads.items():
            if column in unsafe.setdefault(sheet, set()):
                continue
            if any(_reads_unsafe(refs, sheet, unsafe) for refs in all_references):
                unsafe[sheet].add(column)
                changed = True
    return unsafe


def _reads_unsafe(refs: list[tuple[str | None, int]] | None, sheet: str, unsafe: dict[str, set[int]]) -> bool:
    if refs is None:
        return True
    for other, column in refs:
        columns = unsafe.get(other or sheet, set() if (other or sheet) == sheet else None)
        if columns is None:
            return True  # a sheet that does not exist here
        if column in columns or (column == ALL_COLUMNS and columns):
            return True
    return False


# --------------------------------------------------------------------------- reading and writing the file
def _worksheet_parts(archive: zipfile.ZipFile) -> list[str]:
    """The XML part of each worksheet, in workbook order. Chart sheets are not worksheets."""
    workbook_path = "xl/workbook.xml"
    targets = {
        rel.get("Id"): rel.get("Target")
        for rel in etree.fromstring(archive.read("xl/_rels/workbook.xml.rels")).iter(f"{_PACKAGE_REL}Relationship")
    }
    parts = []
    for sheet in etree.fromstring(archive.read(workbook_path)).iter(f"{_MAIN}sheet"):
        target = targets.get(sheet.get(f"{_REL}id"), "")
        if "worksheets/" not in target:
            continue
        parts.append(target.lstrip("/") if target.startswith("/") else str(PurePosixPath("xl") / target))
    return parts


def read_stored_results(path: Path) -> list[dict[str, tuple[str | None, str]]]:
    """For each worksheet: cell -> (type, value) of each formula's stored result."""
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            for si in etree.fromstring(archive.read("xl/sharedStrings.xml")).iter(f"{_MAIN}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{_MAIN}t")))
        results = []
        for part in _worksheet_parts(archive):
            cells: dict[str, tuple[str | None, str]] = {}
            for cell in etree.fromstring(archive.read(part)).iter(f"{_MAIN}c"):
                if cell.find(f"{_MAIN}f") is None:
                    continue
                value = cell.find(f"{_MAIN}v")
                if value is None or value.text is None:
                    continue
                kind = cell.get("t")
                if kind == "s":
                    cells[cell.get("r")] = ("str", shared[int(value.text)])
                else:
                    cells[cell.get("r")] = (kind, value.text)
            results.append(cells)
    return results


def read_exact_numbers(path: Path) -> list[dict[str, str]]:
    """For each worksheet: cell -> the number exactly as the file wrote it, for cells without a formula."""
    with zipfile.ZipFile(path) as archive:
        sheets = []
        for part in _worksheet_parts(archive):
            cells = {}
            for cell in etree.fromstring(archive.read(part)).iter(f"{_MAIN}c"):
                value = cell.find(f"{_MAIN}v")
                if cell.find(f"{_MAIN}f") is None and cell.get("t") in (None, "n") and value is not None and value.text:
                    cells[cell.get("r")] = value.text
            sheets.append(cells)
    return sheets


def _same_number(written: str, original: str) -> bool:
    """The library rounds to 16 digits. A larger difference means the cell was replaced on purpose."""
    try:
        new, old = float(written), float(original)
    except ValueError:
        return False
    return new == old or abs(new - old) <= _ROUNDING * max(abs(new), abs(old))


def write_stored_results(
    path: Path, results: list[dict[str, tuple[str | None, str]]], numbers: list[dict[str, str]] | None = None
) -> None:
    """Puts results back into the formula cells of a saved file, and numbers back to their exact digits."""
    temporary = path.with_name(path.name + ".tmp")
    numbers = numbers or [{} for _ in results]
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target:
        parts = _worksheet_parts(source)
        by_part = dict(zip(parts, results))
        exact_by_part = dict(zip(parts, numbers))
        for item in source.infolist():
            data = source.read(item.filename)
            cells = by_part.get(item.filename)
            exact = exact_by_part.get(item.filename)
            if cells or exact:
                root = etree.fromstring(data)
                for cell in root.iter(f"{_MAIN}c"):
                    original = (exact or {}).get(cell.get("r"))
                    if original is not None and cell.find(f"{_MAIN}f") is None and cell.get("t") in (None, "n"):
                        value = cell.find(f"{_MAIN}v")
                        if value is not None and value.text and _same_number(value.text, original):
                            value.text = original
                    if cell.find(f"{_MAIN}f") is None or cell.get("r") not in (cells or {}):
                        continue
                    kind, text = cells[cell.get("r")]
                    value = cell.find(f"{_MAIN}v")
                    if value is None:
                        value = etree.SubElement(cell, f"{_MAIN}v")
                    value.text = text
                    if kind in (None, "n"):
                        cell.attrib.pop("t", None)
                    else:
                        cell.set("t", kind)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            target.writestr(item, data)
    os.replace(temporary, path)


def column_of(coordinate: str) -> int:
    return coordinate_to_tuple(coordinate)[1]
