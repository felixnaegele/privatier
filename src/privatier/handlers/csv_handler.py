from __future__ import annotations

import csv
import io
from pathlib import Path

from ..transform import Transformer
from .base import SameNameMixin
from .text_handler import read_text


def _delimiter(sample: str, suffix: str) -> str:
    if suffix == ".tsv":
        return "\t"
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        return ";" if sample.count(";") > sample.count(",") else ","


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
        header = rows[0]
        categories = [t.classify(h) for h in header]
        out_rows = [[t.text(h) for h in header]]
        for row in rows[1:]:
            out_rows.append(
                [t.cell(categories[i] if i < len(categories) else None, v) for i, v in enumerate(row)]
            )
        if dst is not None:
            buf = io.StringIO()
            csv.writer(buf, delimiter=delimiter, lineterminator="\n").writerows(
                [["" if v is None else str(v) for v in r] for r in out_rows]
            )
            out_encoding = "utf-8-sig" if encoding == "utf-8-sig" else encoding
            dst.write_text(buf.getvalue(), encoding=out_encoding, errors="replace")
