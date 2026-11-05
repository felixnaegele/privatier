from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

from ..transform import Transformer
from .base import SameNameMixin

_HEADER_SEARCH_ROWS = 20


def _find_header_row(ws) -> int | None:
    """The first row that looks like column headers (mostly text)."""
    for r, row in enumerate(ws.iter_rows(min_row=1, max_row=_HEADER_SEARCH_ROWS, values_only=True), start=1):
        filled = [v for v in row if v not in (None, "")]
        texts = [v for v in filled if isinstance(v, str)]
        if filled and len(texts) >= max(1, len(filled) * 0.6) and (len(texts) >= 2 or len(row) == 1):
            return r
    return None


class ExcelHandler(SameNameMixin):
    name = "excel"
    extensions = (".xlsx", ".xlsm")

    def process(self, src: Path, dst: Path | None, t: Transformer) -> None:
        wb = load_workbook(src, keep_vba=src.suffix.lower() == ".xlsm")
        for ws in wb.worksheets:
            header_row = _find_header_row(ws)
            categories: dict[int, str | None] = {}
            if header_row:
                for cell in ws[header_row]:
                    if isinstance(cell.value, str):
                        categories[cell.column] = t.classify(cell.value)
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell, MergedCell):
                        continue
                    if cell.comment is not None:
                        cell.comment.text = t.text(cell.comment.text)
                        cell.comment.author = ""
                    value = cell.value
                    if value is None or (isinstance(value, str) and value.startswith("=")):
                        continue  # empty or a formula
                    if header_row and cell.row > header_row:
                        new = t.cell(categories.get(cell.column), value)
                    else:
                        new = t.text(value) if isinstance(value, str) else value
                    if new != value:
                        if cell.is_date and not hasattr(new, "year"):
                            cell.number_format = "General"  # e.g. birth date reduced to a year
                        cell.value = new
            new_title = t.text(ws.title)[:31]
            if new_title != ws.title:
                ws.title = new_title
        wb.properties.creator = None
        wb.properties.lastModifiedBy = None
        if dst is not None:
            wb.save(dst)
