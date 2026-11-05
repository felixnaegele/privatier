from __future__ import annotations

import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

from ..transform import Transformer
from .base import SameNameMixin

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
    return isinstance(value, str) and value.startswith("=")


def _formula(value: str, t: Transformer) -> str:
    """Formulas keep working, but text written inside them ("Max Müller") is data too."""
    return _FORMULA_TEXT.sub(lambda m: '"' + t.text(m.group(1)) + '"', value)


def _store(cell, new) -> None:
    if new != cell.value:
        if cell.is_date and not hasattr(new, "year"):
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


class ExcelHandler(SameNameMixin):
    name = "excel"
    extensions = (".xlsx", ".xlsm")

    def process(self, src: Path, dst: Path | None, t: Transformer) -> None:
        wb = load_workbook(src, keep_vba=src.suffix.lower() == ".xlsm")
        for ws in wb.worksheets:
            t.begin_table(ws.title)
            header_row = _find_header_row(ws)
            columns = []
            if header_row:
                columns = [
                    t.column(cell.value) if isinstance(cell.value, str) else t.column(None)
                    for cell in ws[header_row]
                ]
            for row in ws.iter_rows():
                cells = [c for c in row if not isinstance(c, MergedCell)]
                for cell in cells:
                    if cell.comment is not None:
                        cell.comment.text = t.text(cell.comment.text)
                        cell.comment.author = ""
                    if _is_formula(cell.value):
                        cell.value = _formula(cell.value, t)
                if header_row and row[0].row > header_row:
                    self._data_row(row, columns, t)
                    continue
                for cell in cells:
                    value = cell.value
                    if value is None or _is_formula(value) or not isinstance(value, str):
                        continue
                    _store(cell, t.header(value) if row[0].row == header_row else t.text(value))
            _page_margins(ws, t)
            new_title = t.header(ws.title)[:31]  # like a column name: short, without context for the AI
            if new_title != ws.title:
                ws.title = new_title
        wb.properties.creator = None
        wb.properties.lastModifiedBy = None
        for prop in _DOC_PROPERTIES:
            value = getattr(wb.properties, prop, None)
            if value:
                setattr(wb.properties, prop, t.text(value))
        if dst is not None:
            wb.save(dst)

    @staticmethod
    def _data_row(row, columns, t: Transformer) -> None:
        # Formulas and merged cells stay out of the row's values, they were handled above.
        values = [None if isinstance(c, MergedCell) or _is_formula(c.value) else c.value for c in row]
        for cell, original, new in zip(row, values, t.row(columns, values)):
            if original is not None and not isinstance(cell, MergedCell):
                _store(cell, new)
