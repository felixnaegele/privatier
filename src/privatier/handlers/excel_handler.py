from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles.numbers import is_date_format
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import from_excel
from openpyxl.cell.cell import MergedCell
from openpyxl.worksheet.formula import ArrayFormula, DataTableFormula

from ..transform import KEEP_FORMULA, Transformer
from .base import SameNameMixin
from .excel_formulas import column_of, read_exact_numbers, read_stored_results, unsafe_columns, write_stored_results

_HEADER_SEARCH_ROWS = 20
_FORMULA_TEXT = re.compile(r'"((?:[^"]|"")*)"')
_PAGE_MARGINS = ("oddHeader", "oddFooter", "evenHeader", "evenFooter", "firstHeader", "firstFooter")
_DOC_PROPERTIES = ("title", "subject", "description", "keywords", "category")


def _find_header_row(ws) -> int | None:
    """The first row that looks like column headers (mostly text)."""
    rows = list(ws.iter_rows(min_row=1, max_row=_HEADER_SEARCH_ROWS + 1, values_only=True))
    for r, row in enumerate(rows[:_HEADER_SEARCH_ROWS], start=1):
        filled = [v for v in row if v not in (None, "")]
        texts = [v for v in filled if isinstance(v, str)]
        if filled and len(texts) >= max(1, len(filled) * 0.6) and (len(texts) >= 2 or len(row) == 1):
            return r
        # A sheet where only one column has a header: text above a row that holds other kinds of values.
        following = rows[r] if r < len(rows) else ()
        if filled and len(texts) == len(filled) and any(isinstance(v, (int, float)) or hasattr(v, "year") for v in following):
            return r
    return None


def _is_formula(value) -> bool:
    return (isinstance(value, str) and value.startswith("=")) or isinstance(value, (ArrayFormula, DataTableFormula))


def _formula_text(value) -> str:
    return value.text or "" if isinstance(value, ArrayFormula) else str(value) if isinstance(value, str) else ""


def _formula(value: str, t: Transformer) -> str:
    """Formulas keep working, but text written inside them ("Max Müller") is data too."""
    return _FORMULA_TEXT.sub(lambda m: '"' + t.text(m.group(1)) + '"', value)


def _store(cell, new) -> None:
    if new != cell.value:
        # Also for a formula cell, which does not count as a date yet: 2015 must not show as a date in 1905.
        if (cell.is_date or is_date_format(cell.number_format)) and not hasattr(new, "year"):
            cell.number_format = "General"  # e.g. birth date reduced to a year
        cell.value = new


def _page_margins(ws, t: Transformer) -> None:
    for margin in _PAGE_MARGINS:
        section = getattr(ws, margin, None)
        if section is None:
            continue
        for part in (section.left, section.center, section.right):
            if part.text:
                part.text = t.text(part.text)


def _clean_places_outside_cells(wb, src: Path, t: Transformer) -> None:
    """Names also hide outside the cells. What can be read is cleaned; what cannot be checked is removed and reported."""
    removed: Counter[str] = Counter()
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                link = None if isinstance(cell, MergedCell) else cell.hyperlink
                if link is not None:
                    for part in ("target", "location", "tooltip", "display"):
                        if getattr(link, part, None):
                            setattr(link, part, t.text(getattr(link, part)))
        for rule in ws.data_validations.dataValidation if ws.data_validations else []:
            for part in ("formula1", "formula2"):
                if getattr(rule, part, None):
                    setattr(rule, part, _formula(getattr(rule, part), t))
            for part in ("prompt", "promptTitle", "error", "errorTitle"):
                if getattr(rule, part, None):
                    setattr(rule, part, t.text(getattr(rule, part)))
        # Pivot tables keep a copy of the raw data; pictures and charts cannot be checked.
        for kind, attribute in (("pivot table", "_pivots"), ("picture", "_images"), ("chart", "_charts")):
            if getattr(ws, attribute, None):
                removed[kind] += len(getattr(ws, attribute))
                setattr(ws, attribute, [])
    for prop in list(wb.custom_doc_props.props if wb.custom_doc_props else []):
        if isinstance(prop.value, str):
            prop.value = t.text(prop.value)
    for name in wb.defined_names.values():
        if name.attr_text:
            name.attr_text = _formula(name.attr_text, t)
    for link in getattr(wb, "_external_links", []):
        book = getattr(link, "externalBook", None)
        if book is not None and getattr(book, "sheetDataSet", None) is not None:
            book.sheetDataSet = None  # values copied from another file
            removed["stored copy of another workbook"] += 1
        if getattr(link, "file_link", None) is not None and link.file_link.Target:
            link.file_link.Target = t.text(link.file_link.Target)
    for kind, count in sorted(removed.items()):
        t.note_removed(kind, count)
    if src.suffix.lower() == ".xlsm":
        t.note_unchecked("this file contains macros, which are kept unchecked and can hold names")


def _follow_renamed_sheets(wb, titles: list[str]) -> None:
    """A formula names the sheets it reads, and that name has to change along with the sheet."""
    renamed = {old: ws.title for old, ws in zip(titles, wb.worksheets) if old != ws.title}
    if not renamed:
        return
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    for old, new in renamed.items():
                        quoted_old, quoted_new = old.replace("'", "''"), new.replace("'", "''")
                        cell.value = cell.value.replace(f"'{quoted_old}'!", f"'{quoted_new}'!")
                        cell.value = re.sub(rf"(?<![\w'.]){re.escape(old)}!", f"'{quoted_new}'!", cell.value)


def _safe_results(stored, titles, formulas, sensitive, t: Transformer) -> list[dict]:
    unsafe = unsafe_columns(formulas, sensitive)
    results = []
    for title, cells in zip(titles, stored):
        kept = {}
        withheld: set[int] = set()
        for coordinate, (kind, value) in cells.items():
            column = column_of(coordinate)
            if column in unsafe.get(title, set()):
                withheld.add(column)
            elif kind == "str":
                kept[coordinate] = (kind, t.header(value))  # a text result is text like any other
            else:
                kept[coordinate] = (kind, value)
        results.append(kept)
        for column in sorted(withheld):
            t.note_withheld_results(f"{title}, column {get_column_letter(column)}")
    return results


def _stored_value(cell, stored: dict):
    """The result a formula last had, as the kind of value it shows."""
    kind, text = stored.get(cell.coordinate, (None, None))
    if text is None or kind == "e":
        return None
    if kind == "str":
        return text
    try:
        number = float(text)
    except ValueError:
        return text
    return from_excel(number) if cell.is_date else number


class ExcelHandler(SameNameMixin):
    name = "excel"
    extensions = (".xlsx", ".xlsm")

    def process(self, src: Path, dst: Path | None, t: Transformer) -> None:
        wb = load_workbook(src, keep_vba=src.suffix.lower() == ".xlsm")
        stored = read_stored_results(src)
        titles = [ws.title for ws in wb.worksheets]
        sensitive: dict[str, set[int]] = {}
        formulas: dict[str, dict[int, list[str]]] = {}
        for ws in wb.worksheets:
            original_title = ws.title
            t.begin_table(ws.title)
            header_row = _find_header_row(ws)
            columns = []
            if header_row:
                columns = [
                    t.column(cell.value) if isinstance(cell.value, str) else t.column(None)
                    for cell in ws[header_row]
                ]
            elif t.table_without_header():
                # Nothing tells what these columns hold, so nothing can be checked: the sheet stays, empty.
                count = 0
                for row in ws.iter_rows():
                    for cell in row:
                        if not isinstance(cell, MergedCell) and cell.value is not None:
                            cell.value = None
                            count += 1
                if count:
                    t.note_removed("cell in a sheet without a header row", count)
            sensitive[original_title] = {
                ws.min_column + i for i, column in enumerate(columns) if t.identifies(i, column)
            }
            sheet_formulas = formulas.setdefault(original_title, {})
            for row in ws.iter_rows():
                cells = [c for c in row if not isinstance(c, MergedCell)]
                for cell in cells:
                    if cell.comment is not None and not t.keeps_comments:
                        cell.comment = None
                    if cell.comment is not None:
                        cell.comment.text = t.text(cell.comment.text)
                        cell.comment.author = ""
                    if _is_formula(cell.value):
                        sheet_formulas.setdefault(cell.column, []).append(_formula_text(cell.value) or "[unknown]")
                        if isinstance(cell.value, ArrayFormula):
                            cell.value.text = _formula(cell.value.text or "", t)
                        elif isinstance(cell.value, str):
                            cell.value = _formula(cell.value, t)
                if header_row and row[0].row > header_row:
                    self._data_row(row, columns, t, stored[titles.index(original_title)])
                    continue
                for cell in cells:
                    value = cell.value
                    if value is None or _is_formula(value):
                        continue
                    if not isinstance(value, str):
                        _store(cell, t.outside_the_rows(value))
                        continue
                    _store(cell, t.header(value) if row[0].row == header_row else t.text(value))
            _page_margins(ws, t)
            new_title = t.header(ws.title)[:31]  # like a column name: short, without context for the AI
            if new_title != ws.title:
                ws.title = new_title
        _follow_renamed_sheets(wb, titles)
        _clean_places_outside_cells(wb, src, t)
        wb.properties.creator = None
        wb.properties.lastModifiedBy = None
        for prop in _DOC_PROPERTIES:
            value = getattr(wb.properties, prop, None)
            if value:
                setattr(wb.properties, prop, t.text(value))
        results = _safe_results(stored, titles, formulas, sensitive, t)
        if dst is not None:
            wb.save(dst)
            write_stored_results(dst, results, read_exact_numbers(src))

    @staticmethod
    def _data_row(row, columns, t: Transformer, stored: dict) -> None:
        # Formulas and merged cells stay out of the row's values, they were handled above.
        values = [None if isinstance(c, MergedCell) or _is_formula(c.value) else c.value for c in row]
        for i, (cell, original, new) in enumerate(zip(row, values, t.row(columns, values))):
            if original is not None and not isinstance(cell, MergedCell):
                _store(cell, new)
            elif not isinstance(cell, MergedCell) and _is_formula(cell.value):
                replacement = t.formula_replacement(i, _stored_value(cell, stored))
                if replacement is not KEEP_FORMULA:
                    _store(cell, replacement)
