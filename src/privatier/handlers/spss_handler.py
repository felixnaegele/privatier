from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyreadstat

from ..transform import Transformer
from .base import SameNameMixin


class SpssHandler(SameNameMixin):
    name = "spss"
    extensions = (".sav", ".zsav")

    def process(self, src: Path, dst: Path | None, t: Transformer) -> None:
        # user_missing=True: codes like 99 = "refused" must stay in the data, not turn into blanks.
        df, meta = pyreadstat.read_sav(str(src), user_missing=True)
        labels = meta.column_names_to_labels or {}
        value_labels = dict(meta.variable_value_labels or {})
        missing_ranges = dict(meta.missing_ranges or {})
        formats = dict(meta.original_variable_types or {})

        names = list(df.columns)
        columns = [t.column(col, labels.get(col)) for col in names]
        new_rows = [t.row(columns, list(values)) for values in df.itertuples(index=False, name=None)]
        for i, col in enumerate(names):
            changed = pd.Series([row[i] for row in new_rows], index=df.index, dtype=object)
            if columns[i].category is None:
                if changed.map(lambda v: isinstance(v, str)).any() or df[col].dtype == object:
                    df[col] = changed
                    if changed.map(lambda v: isinstance(v, str)).any():
                        formats.pop(col, None)  # a stored text width like A5 may be too short for a code
                continue
            # The column's content changed type (e.g. numbers became tokens): these no longer apply.
            value_labels.pop(col, None)
            missing_ranges.pop(col, None)
            formats.pop(col, None)
            if changed.map(lambda v: isinstance(v, str)).any():
                changed = changed.map(lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
            else:
                changed = pd.to_numeric(changed, errors="coerce")
            df[col] = changed

        new_labels = [t.header(labels[c]) if labels.get(c) else None for c in df.columns]
        for col, mapping in value_labels.items():
            value_labels[col] = {k: t.header(v) if isinstance(v, str) else v for k, v in mapping.items()}
        file_label = t.text(meta.file_label) if meta.file_label else None
        notes = [t.text(n) for n in (meta.notes or [])]

        if dst is not None:
            measures = {c: m for c, m in (meta.variable_measure or {}).items() if c in df.columns}
            pyreadstat.write_sav(
                df,
                str(dst),
                file_label=file_label,
                note=notes or None,
                column_labels=new_labels,
                variable_value_labels=value_labels,
                missing_ranges=missing_ranges,
                variable_measure=measures,
                variable_format={c: f for c, f in formats.items() if c in df.columns},
                compress=src.suffix.lower() == ".zsav",
            )
