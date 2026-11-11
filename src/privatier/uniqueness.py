"""How many patients can be singled out by what stays in a table? Works with counts and never shows values.

Someone who knows a patient's sex, age and date of surgery can recognise that patient without a name.
This module reads tables, recognises the characteristics such a person could know, and counts how many
patients share each combination. It also says what it could not check: "could not check" never counts
as safe.

    from a folder  ->  read_tables()  ->  check_tables()    what a folder holds, or would hold at a level
                                          build_plan()      what each level does, used for writing the copy
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pyreadstat
from openpyxl import load_workbook

from .handlers.csv_handler import _delimiter, _find_header_row as _csv_header_row
from .handlers.excel_handler import _find_header_row as _excel_header_row
from .handlers.text_handler import read_text
from .identity import name_key
from .privacy import LEVELS, MIN_GROUP, UNREAD, Level, _date_of, date_action, is_blank, is_date_object, reduce_value
from .pseudonyms import TOKEN_RE
from .tables import column_key, classify_header, column_role, is_age_column, is_sex_column, is_visit_id, looks_like_date_column
from .transform import _is_legend_row

_TABLE_TYPES = {".xlsx", ".xlsm", ".csv", ".tsv", ".sav", ".zsav"}
_MOST = 0.5
_MAX_CATEGORIES = 20
_MONTH_TEXT = re.compile(r"^\s*(19|20)\d{2}-\d{2}\s*$")
_DATE_TOKEN = re.compile(r"^\s*DATE_\d+")
_NUMBER_TEXT = re.compile(r"^\s*[-+]?\d+(?:[.,]\d+)?\s*(?:%|mm|cm|kg|ml|y|j)?\s*$", re.IGNORECASE)
_BAND = re.compile(r"^\s*\d{1,4}-\d{1,4}\s*$|^\s*90\+\s*$")
_YEAR_HEADER = re.compile(r"(^|_)(jahr|year)($|_)")
_AGE_GROUPS = re.compile(r"group|gruppe|klasse|class|categ|kateg")
_NOT_A_PATIENT = re.compile(r"center|centre|site|hospital|study|zentrum|klinik")
_CHARACTERISTICS = {"sex", "age", "birth", "date", "year"}

ColumnRef = tuple[str, str, int]


def list_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part.startswith(".") or part.startswith("~$") for part in rel.parts):
            continue  # hidden files (.DS_Store) and Office lock files
        if path.is_file() and not path.is_symlink():
            files.append(path)
    return files


def select_files(root: Path, only=None) -> list[Path]:
    """The files of a folder, or only the ones named. Whatever is not named is not read at all."""
    root = Path(root).resolve()
    files = list_files(root)
    if only is None:
        return files
    wanted = set()
    for item in only:
        path = Path(item)
        path = (path if path.is_absolute() else root / path).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"This file is not inside the folder: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        wanted.add(path)
    chosen = [f for f in files if f.resolve() in wanted]
    if len(chosen) != len(wanted):
        raise ValueError("A hidden file, a lock file or a link cannot be chosen.")
    return chosen


@dataclass
class TableColumn:
    index: int
    header: str
    kind: str | None = None  # sex, age, birth, date, year, text
    patient: str | None = None  # id, name
    unnamed: bool = False


@dataclass
class Table:
    file: str
    name: str
    columns: list[TableColumn] = field(default_factory=list)
    rows: list[tuple[int, list]] = field(default_factory=list)  # (the row's number, its values)
    problem: str | None = None

    @property
    def title(self) -> str:
        return f"{self.file}, {self.name}" if self.name else self.file


# --------------------------------------------------------------------------- reading
def _is_year_value(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return float(value).is_integer() and 1900 <= value <= 2100
    return isinstance(value, str) and bool(re.fullmatch(r"\s*(19|20)\d{2}\s*", value))


def _is_date_value(value) -> bool:
    if is_date_object(value):
        return True
    if not isinstance(value, str):
        return False
    found = _date_of(value)  # also 03/04/2015, which can be read two ways: it is a date either way
    return bool(found and found.dates) or bool(_MONTH_TEXT.match(value) or _DATE_TOKEN.match(value))


def _looks_like_age(values: list) -> bool:
    """A column about age, not "age_group" with codes 1 to 3 or "age_related" with 0 and 1."""
    if sum(isinstance(v, str) and bool(_BAND.match(v)) for v in values) > len(values) * _MOST:
        return True
    numbers = []
    for value in values:
        try:
            numbers.append(float(str(value).replace(",", ".")))
        except ValueError:
            pass
    if len(numbers) < len(values) * _MOST or not numbers:
        return False
    return max(numbers) > 10


def _looks_like_free_text(values: list) -> bool:
    """Words that vary from row to row. A column that repeats a few values holds categories."""
    words = [
        v for v in values
        if isinstance(v, str) and not _NUMBER_TEXT.match(v) and not TOKEN_RE.fullmatch(v.strip()) and not _is_date_value(v)
    ]
    if not words or len(words) < len(values) * _MOST:
        return False
    distinct = len(set(words))
    return distinct > _MAX_CATEGORIES or distinct / len(words) >= _MOST


def _classify(header, label, values: list, index: int, answer: str | None) -> TableColumn:
    text = "" if header is None else str(header)
    named = bool(text.strip()) and not text.startswith("Unnamed")
    column = TableColumn(index, text.strip() or f"(column {index + 1})", unnamed=not named)
    category = classify_header(text if named else None, label)
    if answer == "DOB":
        category = "DOB"
    elif answer in ("KEEP_DATES", "KEEP"):
        category = None
    if category in ("DOB", "BIRTH_YEAR"):
        column.kind = "birth"
    elif category == "ID" or answer == "ID":
        column.patient = None if is_visit_id(text, label) else "id"
    elif category == "PERSON" or answer == "PERSON":
        column.patient = "name" if column_role(text, label) in ("first", "last", "full") else None
    elif category is not None:
        pass
    elif column_role(text, label) == "gender" or is_sex_column(text, label):
        column.kind = "sex"
    elif values:
        dates = sum(_is_date_value(v) for v in values)
        if answer == "KEEP":
            pass
        elif is_age_column(text, label) and not _AGE_GROUPS.search(column_key(text, label) or "") and _looks_like_age(values):
            column.kind = "age"
        elif dates >= len(values) * _MOST:
            column.kind = "date"
        elif (looks_like_date_column(text, label) or _YEAR_HEADER.search(column_key(text, label) or "")) and (
            sum(_is_year_value(v) for v in values) >= len(values) * 0.8
        ):
            column.kind = "year"
        elif _looks_like_free_text(values):
            column.kind = "text"
    return column


def _table(file: str, name: str, headers: list, labels: dict, rows: list[list], answers: dict | None) -> Table:
    table = Table(file, name)
    width = max([len(headers), *(len(r) for r in rows)]) if rows or headers else 0
    number = 0
    for values in rows:
        if _is_legend_row(values):
            continue  # "(dd/mm/yyyy)": explains the columns, holds no data
        number += 1
        table.rows.append((number, values))
    for i in range(width):
        header = headers[i] if i < len(headers) else None
        values = [v[i] for _, v in table.rows if i < len(v) and not is_blank(v[i])]
        table.columns.append(
            _classify(header, labels.get(header), values, i, (answers or {}).get((file, name, i)))
        )
    return table


def _read_excel(path: Path, file: str, answers) -> list[Table]:
    tables = []
    for ws in load_workbook(path, data_only=True).worksheets:
        header_row = _excel_header_row(ws)
        all_rows = list(ws.iter_rows(values_only=True))
        if not any(v not in (None, "") for row in all_rows for v in row):
            continue
        if header_row is None:
            tables.append(Table(file, ws.title, problem="no header row"))
            continue
        headers = list(all_rows[header_row - ws.min_row]) if header_row >= ws.min_row else []
        rows = [list(r) for r in all_rows[header_row - ws.min_row + 1 :]]
        tables.append(_table(file, ws.title, [h if isinstance(h, str) else None for h in headers], {}, rows, answers))
    return tables


def _read_csv(path: Path, file: str, answers) -> list[Table]:
    text, _ = read_text(path)
    rows = list(csv.reader(io.StringIO(text), delimiter=_delimiter(text[:20000], path.suffix.lower())))
    if not rows:
        return []
    header_at = _csv_header_row(rows)
    if header_at is None:
        return [Table(file, "", problem="no header row")]
    return [_table(file, "", list(rows[header_at]), {}, [list(r) for r in rows[header_at + 1 :]], answers)]


def _read_spss(path: Path, file: str, answers) -> list[Table]:
    frame, meta = pyreadstat.read_sav(str(path), user_missing=True)
    labels = meta.column_names_to_labels or {}
    rows = [list(values) for values in frame.itertuples(index=False, name=None)]
    return [_table(file, "", list(frame.columns), labels, rows, answers)]


def read_tables(folder: Path, answers: dict | None = None, only=None) -> tuple[list[Table], list[str]]:
    """All tables in a folder, and the files that are not tables. A table that cannot be read says so.

    With `only`, just these files of the folder: the others are not read and not listed."""
    tables: list[Table] = []
    others: list[str] = []
    folder = Path(folder)
    if only is not None:
        folder = folder.resolve()
    for path in list_files(folder) if only is None else select_files(folder, only):
        file = str(path.relative_to(folder))
        suffix = path.suffix.lower()
        if suffix not in _TABLE_TYPES:
            others.append(file)
            continue
        reader = _read_excel if suffix in (".xlsx", ".xlsm") else _read_spss if suffix in (".sav", ".zsav") else _read_csv
        try:
            tables.extend(reader(path, file, answers))
        except Exception:  # the reason is not shown, as it can quote a cell
            tables.append(Table(file, "", problem="could not be read"))
    return tables, others


# --------------------------------------------------------------------------- what a level does
@dataclass
class Plan:
    level: Level
    actions: dict[ColumnRef, str] = field(default_factory=dict)
    blanks: dict[tuple[str, str], dict[int, set[int]]] = field(default_factory=dict)  # table -> row -> columns
    removed_tables: set[tuple[str, str]] = field(default_factory=set)

    def action(self, file: str, table: str, index: int) -> str | None:
        return self.actions.get((file, table, index))

    def blanked(self, file: str, table: str, row: int, index: int) -> bool:
        return index in self.blanks.get((file, table), {}).get(row, ())


def _column_action(column: TableColumn, level: Level, keep_text: set[tuple[str, str, int]], ref: ColumnRef) -> str | None:
    if column.kind == "birth":
        return "decade" if level.births == "decade" else None
    if column.kind == "age":
        return "band" if level.ages == "band" else None
    if column.kind == "date":
        if column.unnamed and level.number == 2:
            return None  # stays a code: it could be a birth date, whose month should not show
        return date_action(level)
    if column.kind == "year":
        return "remove" if level.dates == "remove" else None
    if column.kind == "text" and not level.keeps_free_text and ref not in keep_text:
        return "empty"
    return None


def _facts(table: Table, columns: list[TableColumn], number: int, values: list, plan: Plan | None) -> tuple:
    out = []
    for column in columns:
        value = values[column.index] if column.index < len(values) else None
        if plan is not None:
            if plan.blanked(table.file, table.name, number, column.index):
                value = None
            elif action := plan.action(table.file, table.name, column.index):
                reduced = reduce_value(action, value)
                value = value if reduced is UNREAD else reduced
        out.append(None if is_blank(value) else str(value).strip().casefold())
    return tuple(out)


def _base_code(value: str) -> str | None:
    m = TOKEN_RE.fullmatch(value)
    return f"{m.group(1).upper()}_{m.group(2)}" if m else None


def _patient_keys(table: Table) -> tuple[list, str]:
    """Who each row is about, so that a patient with five rows counts once. Without a patient column: rows."""
    ids = [c for c in table.columns if c.patient == "id" and not _NOT_A_PATIENT.search(column_key(c.header) or "")]
    names = [c for c in table.columns if c.patient == "name"]

    def distinct(column: TableColumn) -> int:
        return len({str(v[column.index]).strip() for _, v in table.rows if column.index < len(v) and not is_blank(v[column.index])})

    chosen = max(ids, key=distinct, default=None)
    if chosen is not None and distinct(chosen) < 2:
        chosen = None  # the same value in every row says nothing about who is who
    keys = []
    for number, values in table.rows:
        key = None
        if chosen is not None:
            if chosen.index < len(values) and not is_blank(values[chosen.index]):
                text = str(values[chosen.index]).strip()
                key = ("p", _base_code(text) or text.casefold())
        elif names:
            parts = [str(values[c.index]).strip() for c in names if c.index < len(values) and not is_blank(values[c.index])]
            codes = {_base_code(p) for p in parts}
            if parts and None not in codes:
                key = ("p", tuple(sorted(codes)))
            elif parts:
                key = ("p", name_key(" ".join(parts)))
        keys.append(key if key is not None else ("row", number))
    named = sum(k[0] == "p" for k in keys)
    return keys, "patients" if keys and named >= len(keys) * _MOST else "rows"


def _small_rows(table: Table, columns: list[TableColumn], keys: list, plan: Plan | None) -> tuple[set[int], int, int, int]:
    """Rows in groups that are too small, then patients in total, patients alone, patients in a small group."""
    sharing: dict[tuple, set] = defaultdict(set)
    rows = []
    for (number, values), key in zip(table.rows, keys):
        facts = _facts(table, columns, number, values, plan)
        if all(f is None for f in facts):
            continue  # nothing about this row can be compared, so nothing singles it out
        sharing[facts].add(key)
        rows.append((number, key, facts))
    alone, small, patients, small_rows = set(), set(), set(), set()
    for number, key, facts in rows:
        patients.add(key)
        size = len(sharing[facts])
        if size == 1:
            alone.add(key)
        if size < MIN_GROUP:
            small.add(key)
            small_rows.add(number)
    return small_rows, len(patients), len(alone), len(small)


def _compared(table: Table, extra: set[ColumnRef]) -> list[TableColumn]:
    return [c for c in table.columns if c.kind in _CHARACTERISTICS or (table.file, table.name, c.index) in extra]


def build_plan(
    tables: list[Table], level_number: int, extra: set[ColumnRef] | None = None, keep_text: set[ColumnRef] | None = None
) -> Plan:
    level = LEVELS[level_number]
    plan = Plan(level)
    extra, keep_text = extra or set(), keep_text or set()
    for table in tables:
        if table.problem:
            if not level.keeps_free_text:  # at levels 3 and 4 what cannot be checked does not go out
                plan.removed_tables.add((table.file, table.name))
            continue
        for column in table.columns:
            ref = (table.file, table.name, column.index)
            if action := _column_action(column, level, keep_text, ref):
                plan.actions[ref] = action
        if level.blanks_rare:
            _blank_rare(table, plan, extra)
    return plan


def _blank_rare(table: Table, plan: Plan, extra: set[ColumnRef]) -> None:
    """A rare value in a ticked column first, as it is what makes the row stand out. Then age. Sex last."""
    compared = _compared(table, extra)
    keys, _ = _patient_keys(table)
    order = [
        [c for c in compared if c.kind not in _CHARACTERISTICS],
        [c for c in compared if c.kind in ("age", "birth")],
        [c for c in compared if c.kind in ("date", "year")],
        [c for c in compared if c.kind == "sex"],
    ]
    blanks = plan.blanks.setdefault((table.file, table.name), {})
    for columns in order:
        if not columns:
            continue
        small, *_ = _small_rows(table, compared, keys, plan)
        if not small:
            break
        for number in small:
            blanks.setdefault(number, set()).update(c.index for c in columns)


# --------------------------------------------------------------------------- the check
@dataclass
class TableCheck:
    title: str
    status: str  # checked, nothing_to_compare, could_not_check
    reason: str = ""
    unit: str = "patients"
    total: int = 0
    singled_out: int = 0
    in_small_group: int = 0
    characteristics: list[str] = field(default_factory=list)
    free_text: list[str] = field(default_factory=list)
    blanked_rows: int = 0
    not_compared: int = 0  # clinical columns: someone could know these too

    @property
    def percent(self) -> float:
        return 100 * self.singled_out / self.total if self.total else 0.0

    @property
    def percent_small(self) -> float:
        return 100 * self.in_small_group / self.total if self.total else 0.0


@dataclass
class FolderCheck:
    tables: list[TableCheck]
    other_files: list[str]
    linked: TableCheck | None = None

    @property
    def checked(self) -> list[TableCheck]:
        return [t for t in [*self.tables, self.linked] if t is not None and t.status == "checked"]

    @property
    def could_not_check(self) -> list[TableCheck]:
        return [t for t in self.tables if t.status == "could_not_check"]

    @property
    def worst(self) -> TableCheck | None:
        return max(self.checked, key=lambda t: (t.percent, t.percent_small), default=None)

    @property
    def everyone_in_a_group(self) -> bool:
        return bool(self.checked) and all(t.in_small_group == 0 for t in self.checked)


def _check_table(table: Table, plan: Plan | None, extra: set[ColumnRef]) -> tuple[TableCheck, dict]:
    if table.problem:
        return TableCheck(table.title, "could_not_check", table.problem), {}
    facts_of_patient: dict = {}
    if plan is not None and (table.file, table.name) in plan.removed_tables:
        return TableCheck(table.title, "nothing_to_compare"), {}
    columns = _compared(table, extra)
    if plan is not None:
        columns = [
            c for c in columns
            if plan.action(table.file, table.name, c.index) not in ("remove", "empty")
        ]
    columns = [c for c in columns if any(
        f[0] is not None for f in (
            _facts(table, [c], number, values, plan) for number, values in table.rows
        )
    )]
    free_text = [
        c.header for c in table.columns
        if c.kind == "text" and not (plan and plan.action(table.file, table.name, c.index) == "empty")
    ]
    blanked = len(plan.blanks.get((table.file, table.name), {})) if plan else 0
    not_compared = sum(
        1 for c in table.columns
        if c not in columns and not c.patient and c.kind is None and any(c.index < len(v) and not is_blank(v[c.index]) for _, v in table.rows)
    )
    if not columns:
        return TableCheck(table.title, "nothing_to_compare", free_text=free_text, blanked_rows=blanked, not_compared=not_compared), {}
    keys, unit = _patient_keys(table)
    _, total, alone, small = _small_rows(table, columns, keys, plan)
    for (number, values), key in zip(table.rows, keys):
        if key[0] == "p":
            for column, fact in zip(columns, _facts(table, columns, number, values, plan)):
                if fact is not None:
                    label = column.kind if column.kind in ("sex", "age", "birth") else column_key(column.header)
                    facts_of_patient.setdefault(key, set()).add((label, fact))
    return (
        TableCheck(
            table.title, "checked", unit=unit, total=total, singled_out=alone, in_small_group=small,
            characteristics=[c.header for c in columns], free_text=free_text, blanked_rows=blanked, not_compared=not_compared,
        ),
        facts_of_patient,
    )


def _check_linked(per_table: list[dict]) -> TableCheck | None:
    """The same code in two tables joins what each says about that patient."""
    tables_of: dict = defaultdict(int)
    facts: dict = defaultdict(set)
    for one in per_table:
        for key, found in one.items():
            tables_of[key] += 1
            facts[key] |= found
    if not any(count > 1 for count in tables_of.values()):
        return None
    sharing: dict = defaultdict(int)
    for found in facts.values():
        sharing[frozenset(found)] += 1
    alone = sum(1 for found in facts.values() if sharing[frozenset(found)] == 1)
    small = sum(1 for found in facts.values() if sharing[frozenset(found)] < MIN_GROUP)
    characteristics = sorted({label for found in facts.values() for label, _ in found})
    return TableCheck("All tables, joined by patient code", "checked", total=len(facts), singled_out=alone, in_small_group=small, characteristics=characteristics)


def check_tables(tables: list[Table], others: list[str], plan: Plan | None = None, extra: set[ColumnRef] | None = None) -> FolderCheck:
    extra = extra or set()
    checks, per_table = [], []
    for table in tables:
        check, facts = _check_table(table, plan, extra)
        checks.append(check)
        per_table.append(facts)
    return FolderCheck(checks, others, _check_linked(per_table))


def check_folder(folder: Path, extra: set[ColumnRef] | None = None, only=None) -> FolderCheck:
    tables, others = read_tables(folder, None, only)
    return check_tables(tables, others, None, extra)


# --------------------------------------------------------------------------- the label
@dataclass
class Verdict:
    anonymous: bool
    label: str
    reasons: list[str]


def verdict(level_number: int, check: FolderCheck, named_files: int = 0, unchecked: list[str] | None = None) -> Verdict:
    """The word "anonymous" appears only at level 4, and only if nothing speaks against it."""
    level = LEVELS[level_number]
    if level.keeps_key:
        return Verdict(False, f"{level.name}: still personal data", ["A key exists, so patients can be identified again."])
    reasons = []
    if level_number != 4:
        reasons.append("Only level 4 can count as anonymous.")
    if not check.checked:
        reasons.append("No table held characteristics that could be compared, so the check shows nothing either way.")
    for table in check.could_not_check:
        reasons.append(f"Could not check {table.title} ({table.reason}).")
    for table in check.checked:
        if table.in_small_group:
            reasons.append(
                f"{table.title}: {table.in_small_group} of {table.total} {table.unit} share their characteristics with "
                f"fewer than {MIN_GROUP - 1} others."
            )
    for table in check.tables:
        if table.free_text:
            reasons.append(f"{table.title}: free text remains in {', '.join(table.free_text)}.")
    if check.other_files:
        reasons.append(f"{len(check.other_files)} file(s) that are not tables remain, and these cannot be checked.")
    if named_files:
        reasons.append(f"{named_files} file or folder name(s) contain a name or value from the data.")
    reasons.extend(unchecked or [])
    if reasons:
        return Verdict(False, "Reduced detail, not anonymous", reasons)
    return Verdict(
        True,
        "Anonymous by this check",
        [
            f"Every patient shares sex, age and every date column with at least {MIN_GROUP - 1} others, in every table.",
            f"Other columns were not compared unless you ticked them ({sum(t.not_compared for t in check.tables)} here, "
            "such as clinical values). Someone who knows a rare value could still recognise a patient.",
            "Row order is unchanged: a table sorted by date or name can give hints.",
            "Whether this counts as anonymous in law is for your data protection officer to decide.",
        ],
    )


__all__ = ["FolderCheck", "Plan", "Table", "TableCheck", "Verdict", "build_plan", "check_folder", "check_tables", "list_files", "read_tables", "select_files", "verdict"]
