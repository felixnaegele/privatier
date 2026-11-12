"""Each file as an outline for the review screen: its tables, their columns, and where the findings sit.

Built from two views that share the same column numbers: how the copy treats a column (transform.py), and
the table as the check reads it (uniqueness.py), which gives the headers and the number of filled cells.
Finding ids are worked out from real values: for the user's screen only.
"""

from __future__ import annotations

from .privacy import is_blank
from .review import ColumnOutline, FileOutline, TableOutline
from .transform import Anonymizer
from .uniqueness import Table

# What the user can say a column is (Decisions.columns), where it would change something.
CHOICES = {
    "PERSON": ["ID", "KEEP"],
    "ID": ["PERSON", "KEEP"],
    "ADDRESS": ["KEEP"],
    "EMAIL": ["KEEP"],
    "PHONE": ["KEEP"],
    "BIRTH_DATE": ["KEEP_DATES", "KEEP"],
    "BIRTH_YEAR": [],
    "DATE": ["DOB"],
    "DATE_CODED": ["DOB", "KEEP_DATES"],  # a column without a header that holds dates
    "AGE": [],
    "SEX": [],
    "TEXT": ["PERSON", "ID", "KEEP"],
    "PLAIN": ["PERSON", "ID", "DOB"],
}


def _listed(anon: Anonymizer, found: list) -> list[tuple[str, int]]:
    ordered = sorted(found, key=lambda item: (item[1].type, item[1].value.casefold()))
    return [(anon.finding_id_of(key), count) for key, _, count in ordered]


def _groups(anon: Anonymizer, found: list) -> list[tuple[str, list[tuple[str, int]]]]:
    together: dict[tuple[str, str], list] = {}
    for key, one, count in found:  # the same value outside several columns counts once, with the sum
        entry = together.setdefault(key, [key, one, 0])
        entry[2] += count
    by_type: dict[str, list] = {}
    for key, one, count in together.values():
        by_type.setdefault(one.type, []).append((key, one, count))
    return [(entity_type, _listed(anon, by_type[entity_type])) for entity_type in sorted(by_type)]


def build_outline(anon: Anonymizer, tables: list[Table]) -> list[FileOutline]:
    in_columns, loose = anon.found_by_place()
    tables_of: dict[str, list[Table]] = {}
    for table in tables:
        tables_of.setdefault(table.file, []).append(table)
    out = []
    for file in anon.done_files:
        outside = list(loose.get(file, []))
        shown: set[tuple] = set()
        table_outlines = []
        for table in tables_of.get(file, []):
            if table.problem:
                table_outlines.append(TableOutline(table.name, [], table.problem))
                continue
            treated = anon.seen_columns.get((file, table.name), [])
            columns = []
            for column in table.columns:
                ref = (file, table.name, column.index)
                shown.add(ref)
                found = in_columns.get(ref, [])
                if column.index < len(treated):
                    as_treated = treated[column.index]
                else:  # no row reached this column, so only its header says what it is
                    as_treated = anon._answered_one(ref, anon.column(None if column.unnamed else column.header))
                kind, becomes = anon.column_kind(ref, as_treated, column.kind, bool(found))
                decided = anon.decisions.columns.get(ref)
                choices = CHOICES["DATE_CODED" if kind == "DATE" and "code" in becomes else kind]
                columns.append(
                    ColumnOutline(
                        column.index, column.header, kind, becomes, _listed(anon, found),
                        sum(1 for _, values in table.rows if column.index < len(values) and not is_blank(values[column.index])),
                        decided, ref, [c for c in choices if c != decided],
                    )
                )
            table_outlines.append(TableOutline(table.name, columns))
        for ref, found in in_columns.items():  # a column the check does not list: nothing may go unseen
            if ref[0] == file and ref not in shown:
                outside.extend(found)
        out.append(FileOutline(file, table_outlines, _groups(anon, outside)))
    return out


__all__ = ["CHOICES", "build_outline"]
