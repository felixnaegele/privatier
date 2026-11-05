from __future__ import annotations

import csv
import io
from pathlib import Path

from ..tables import classify_header
from ..transform import Transformer
from .base import SameNameMixin
from .text_handler import read_text

_HEADER_SEARCH_ROWS = 20


def _delimiter(sample: str, suffix: str) -> str:
    if suffix == ".tsv":
        return "\t"
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        return ";" if sample.count(";") > sample.count(",") else ","


def _find_header_row(rows: list[list[str]]) -> int | None:
    """Exports often start with title lines, so the header is not always the first row.

    The header is the row with the most recognised sensitive columns. If none is recognised,
    there is no way to tell a header from data, so the caller treats everything as free text.
    """
    best, best_score = None, 0
    for i, row in enumerate(rows[:_HEADER_SEARCH_ROWS]):
        score = sum(1 for cell in row if classify_header(cell))
        if score > best_score:
            best, best_score = i, score
    if best is not None:
        return best
    # No sensitive column at all: a plain table (e.g. id-free results) keeps its first row as header.
    first = rows[0]
    wide_enough = len(first) >= 2 and all(cell.strip() for cell in first)
    no_numbers = not any(any(c.isdigit() for c in cell) for cell in first)
    return 0 if wide_enough and no_numbers and len(rows) > 1 and _looks_like_labels(first) else None


def _looks_like_labels(row: list[str]) -> bool:
    return all(len(cell.split()) <= 3 for cell in row)


class CsvHandler(SameNameMixin):
    name = "csv"
    extensions = (".csv", ".tsv")

    def process(self, src: Path, dst: Path | None, t: Transformer) -> None:
        text, encoding = read_text(src)
        delimiter = _delimiter(text[:20000], src.suffix.lower())
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        if not rows:
            if dst is not None:
                dst.write_bytes(src.read_bytes())
            return
        t.begin_table("")
        header_at = _find_header_row(rows)
        out_rows = []
        if header_at is None:  # no recognisable header: every cell is treated as free text
            out_rows = [[t.text(v) for v in row] for row in rows]
        else:
            out_rows.extend([t.text(v) for v in row] for row in rows[:header_at])
            header = rows[header_at]
            columns = [t.column(h) for h in header]
            out_rows.append([t.header(h) for h in header])
            out_rows.extend(t.row(columns, row) for row in rows[header_at + 1 :])
        if dst is not None:
            buf = io.StringIO()
            csv.writer(buf, delimiter=delimiter, lineterminator="\n").writerows(
                [["" if v is None else str(v) for v in r] for r in out_rows]
            )
            out_encoding = "utf-8-sig" if encoding == "utf-8-sig" else encoding
            dst.write_text(buf.getvalue(), encoding=out_encoding, errors="replace")
