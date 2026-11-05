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
        df, meta = pyreadstat.read_sav(str(src))
        labels = meta.column_names_to_labels or {}
        value_labels = dict(meta.variable_value_labels or {})

        for col in df.columns:
            category = t.classify(col, labels.get(col))
            original = df[col]
            changed = original.map(lambda v, c=category: t.cell(c, v))
            if category is not None:
                # The column's content changed type (e.g. numbers became tokens): old value labels no longer apply.
                value_labels.pop(col, None)
                if changed.map(lambda v: isinstance(v, str)).any():
                    changed = changed.map(lambda v: "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
            df[col] = changed

        new_labels = [t.header(labels[c]) if labels.get(c) else None for c in df.columns]
        for col, mapping in value_labels.items():
            value_labels[col] = {k: t.header(v) if isinstance(v, str) else v for k, v in mapping.items()}

        if dst is not None:
            measures = {c: m for c, m in (meta.variable_measure or {}).items() if c in df.columns}
            pyreadstat.write_sav(
                df,
                str(dst),
                column_labels=new_labels,
                variable_value_labels=value_labels,
                variable_measure=measures,
                compress=src.suffix.lower() == ".zsav",
            )
