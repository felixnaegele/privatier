"""The two directions of Privatier: anonymise (real -> token) and restore (token -> real).

File handlers don't care which direction they run in. They hand text, table
headers and table rows to a Transformer and write back whatever it returns.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from typing import NamedTuple

from .birthdates import check_birth_date_column
from .detect.base import Detector, Span, resolve_overlaps
from .detect.patterns import _NOT_NAMES, NAME_SEQ, NAME_WORD
from .detect.stopwords import is_ordinary_use, is_stopword
from .identity import Decisions, Person, Question, Record, Registry, name_key, name_parts, parse_birth_date, surname_first
from .privacy import LEVELS, UNREAD, is_blank, is_date_object, reduce_value
from .pseudonyms import GLUED_TOKEN_RE, TOKEN_RE, KnownValueDetector, Pseudonymizer, _normalise, values_to_look_for
from .review import Finding, Review, clean_terms, code_in_words, finding_key, id_of_key
from .tables import (
    CATEGORY_TO_TYPE,
    classify_header,
    column_key,
    column_role,
    is_visit_id,
    looks_like_date_column,
)

_NAME_ROLES = {"first", "last", "full"}
_GENDER_WORDS = {
    "m": "m", "male": "m", "man": "m", "maennlich": "m", "männlich": "m", "herr": "m", "herrn": "m", "hr": "m", "mr": "m",
    "w": "f", "f": "f", "female": "f", "weiblich": "f", "frau": "f", "fr": "f", "mrs": "f", "ms": "f", "miss": "f",
    "patientin": "f",
}
_BEFORE_NAME = re.compile(
    r"(Herrn?|Frau|Hr\.|Fr\.|Mr\.?|Mrs\.?|Ms\.?|Miss|Patientin|Patient)?\s*:?\s*((?:Dr\.(?:\s?med\.)?|Prof\.|PD)\s*)*$"
)
_ACADEMIC = re.compile(r"(?:Dr\.|Prof\.|PD)\s*(?:med\.\s*)?$")
_BIRTH_MARK = re.compile(
    r"(?:geb\.?|geboren(?:\s+am)?|born(?:\s+on)?|DOB|D\.O\.B\.?|Geburtsdatum|Date\s+of\s+birth|\*)\s*:?\s*$",
    re.IGNORECASE,
)
_RELATIVE_BEFORE = re.compile(
    r"(?:Sohn|Tochter|Ehefrau|Ehemann|Ehegatte|Ehegattin|Mann|Partner(?:in)?|Lebensgefährt(?:e|in)|Mutter|Vater|Bruder|"
    r"Schwester|Enkel(?:in)?|Onkel|Tante|Neffe|Nichte|Betreuer(?:in)?|Dolmetscher(?:in)?|son|daughter|wife|husband|"
    r"partner|mother|father|brother|sister|grandson|granddaughter|nephew|niece|uncle|aunt|guardian|caregiver|"
    r"interpreter)[,:]?\s+$",
    re.IGNORECASE,
)
_WORD_BEFORE = re.compile(rf"(?:^|(?<=[^\w.!?:;\n]))\s*({NAME_WORD})[ ]$")
_BIRTH_YEAR_AFTER = re.compile(
    r"[\s,(]*(?:Jg\.?|Jahrgang|geb\.?|geboren|born(?:\s+in)?|b\.|\*)\s*((?:19|20)\d{2})(?!\d|\.)"
)
_WORTH_ASKING_AI = re.compile(r"[^\W\d_]{3}")
_LOOKS_LIKE_NAME = re.compile(rf"{NAME_WORD},\s+{NAME_WORD}|{NAME_SEQ}|[^\W\d_]+(?:\s+[^\W\d_]+){{0,1}}\s+{NAME_WORD}")
_ONLY_SEPARATORS = re.compile(r"^[\s,;(]*$")
_NEAR = 80


class Column(NamedTuple):
    """What a table column holds."""

    category: str | None = None  # ID, DOB, PERSON, ... (see tables.py)
    role: str | None = None  # for people: first, last, full, other; or gender
    key: str = ""
    visit_id: bool = False
    dates: bool = False  # the header says this column holds dates other than the birth date
    keep: bool = False  # the user said to leave this column exactly as it is


_DATE_IN_TEXT = re.compile(r"^\s*\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|^\s*\d{4}-\d{2}-\d{2}")
_LEGEND = re.compile(r"^\s*\(.*\)\s*$|^\s*\d+\s*=|=\s*\d|^\s*\[.*\]\s*$")
_MAX_CATEGORIES = 20
_MIN_WORDS_FOR_AI = 2
_ALMOST_ALL = 0.8
_MOST = 0.5
_MIN_VALUES = 5


_NUMBER_AS_TEXT = re.compile(r"\s*[-+]?\d+(?:[.,]\d+)?\s*")


class _Profile:
    """What the values of one table column look like, to judge columns the header says nothing about."""

    def __init__(self, column: Column, label: str):
        self.column, self.label = column, label
        self.filled, self.dates, self.names, self.whole = 0, 0, 0, 0
        self.words = 0  # cells that hold text, not a number written as text
        self.values: set[str] = set()
        self.texts: set[str] = set()  # as the values are written when they become codes

    def add(self, value) -> None:
        self.filled += 1
        self.values.add(str(value))
        self.texts.add(_cell_text(value).strip())
        if hasattr(value, "year"):
            self.dates += 1
        elif isinstance(value, str):
            self.dates += bool(_DATE_IN_TEXT.match(value))
            self.words += not _NUMBER_AS_TEXT.fullmatch(value)
            self.names += bool(_LOOKS_LIKE_NAME.fullmatch(value.strip())) and not is_stopword(value)
        elif isinstance(value, (int, float)) and float(value).is_integer():
            self.whole += 1

    def share(self, count: int) -> float:
        return count / self.filled if self.filled else 0.0

    @property
    def varied(self) -> float:
        return self.share(len(self.values))


KEEP_FORMULA = object()


class Transformer:
    def __init__(self) -> None:
        self.stats: Counter[str] = Counter()
        self.warnings: list[str] = []
        self.tokens: set[str] = set()

    def reset_file_stats(self) -> None:
        self.stats, self.warnings, self.tokens = Counter(), [], set()

    def text(self, value: str) -> str:
        raise NotImplementedError

    def header(self, value: str) -> str:
        """Column names and variable/value labels."""
        return self.text(value)

    def begin_table(self, name: str) -> None:
        """Handlers call this before each table or sheet."""

    def identifies(self, index: int, column: Column) -> bool:
        """Whether a column holds identifying values, so that nothing derived from it may stay."""
        return column.category not in (None, "BIRTH_YEAR")

    def note_withheld_results(self, where: str) -> None:
        """A formula depends on identifying data, so its stored result was not kept."""

    keeps_comments = True

    def table_without_header(self) -> bool:
        """A table whose columns cannot be told apart. True if it has to go, because it cannot be checked."""
        return False

    def outside_the_rows(self, value):
        """A number or date above the header row."""
        return value

    def formula_replacement(self, index: int, value, is_date_cell: bool = False):
        """What a formula cell becomes when its column loses detail. KEEP_FORMULA if it stays."""
        return KEEP_FORMULA

    def reduced_column(self, index: int) -> bool:
        return False

    def blanks_in_column(self, index: int) -> bool:
        return False

    def note_removed(self, kind: str, count: int) -> None:
        """Something that cannot be checked was left out of the copy."""

    def note_unchecked(self, note: str) -> None:
        """Something that cannot be checked stayed in the copy."""

    def file_name(self, value: str) -> str:
        return self.text(value)

    def labelled(self, category: str, value: str):
        """A value whose label ("Fallnummer" in a Word table) says it is sensitive."""
        return self.text(value)

    def classify(self, header: str | None, label: str | None = None) -> str | None:
        return None

    def column(self, header: str | None, label: str | None = None) -> Column:
        return Column(
            self.classify(header, label),
            column_role(header, label),
            column_key(header, label),
            is_visit_id(header, label),
            looks_like_date_column(header, label),
        )

    def cell(self, category: str | None, value):
        return self.text(value) if isinstance(value, str) else value

    def row(self, columns: list[Column], values: list) -> list:
        """One table row. Handled as a whole, because the cells of a row belong to one person."""
        return [self.cell(_column_at(columns, i).category, v) for i, v in enumerate(values)]


def _plain(text: str) -> str:
    return " ".join(text.split()).casefold()


_AGE_HEADER = re.compile(r"(^|_)(age|alter)($|_)")


def _single_date(value) -> dt.date | None:
    if hasattr(value, "year") and hasattr(value, "day"):
        return dt.date(int(value.year), int(value.month), int(value.day))
    if isinstance(value, str):
        birth = parse_birth_date(value)
        if birth and len(birth.dates) == 1:
            return dt.date.fromisoformat(next(iter(birth.dates)))
    return None


def _letters(index: int) -> str:
    """0 -> A, 26 -> AA, as columns are named in a spreadsheet."""
    out = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        out = chr(65 + rest) + out
    return out


def _is_legend_row(values: list) -> bool:
    filled = [v for v in values if not _blank(v)]
    texts = [v for v in filled if isinstance(v, str) and _LEGEND.search(v)]
    return len(filled) >= _MIN_VALUES and len(texts) / len(filled) >= _MOST


def _with_name_roles(columns: list[Column]) -> list[Column]:
    """A column called just "Name" next to "Vorname" holds the surname, and the other way round."""
    roles = {c.role for c in columns if c.category == "PERSON"}
    if "full" not in roles or ("first" in roles) == ("last" in roles):
        return columns
    other = "last" if "first" in roles else "first"
    return [c._replace(role=other) if c.category == "PERSON" and c.role == "full" else c for c in columns]


def _column_at(columns: list[Column], i: int) -> Column:
    return columns[i] if i < len(columns) else Column()


_blank = is_blank


def _cell_text(value) -> str:
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def _shown(value) -> str:
    """A cell as it is listed for the user. A date without a time shows as a date."""
    if hasattr(value, "year") and hasattr(value, "day"):
        if not getattr(value, "hour", 0) and not getattr(value, "minute", 0) and not getattr(value, "second", 0):
            return f"{int(value.year):04d}-{int(value.month):02d}-{int(value.day):02d}"
        return str(value)
    return _cell_text(value).strip()


class ColumnValues:
    """Every value that sits in an identifying table column, and any longer piece of text that contains one.
    This is what the review screen calls source "column"."""

    def __init__(self) -> None:
        self._keys: set[tuple[str, str]] = set()
        self._pairs: set[tuple[str, str]] = set()
        self._births: set[str] = set()
        self._detector: KnownValueDetector | None = None
        self._answers: dict[tuple[str, str], bool] = {}

    def add(self, entity_type: str, text) -> None:
        text = " ".join(str(text).split())
        if not text or TOKEN_RE.fullmatch(text):
            return
        key = (entity_type, _normalise(entity_type, text))
        if key not in self._keys:
            self._keys.add(key)
            self._pairs.add((entity_type, text))
            self._detector = None
            self._answers.clear()

    def add_birth(self, value) -> None:
        birth = parse_birth_date(value)
        if birth and not birth.dates <= self._births:
            self._births |= birth.dates
            self._answers.clear()

    def holds(self, entity_type: str, text: str) -> bool:
        text = " ".join(str(text).split())
        asked = (entity_type, text)
        if asked not in self._answers:
            self._answers[asked] = self._holds(entity_type, text)
        return self._answers[asked]

    def _holds(self, entity_type: str, text: str) -> bool:
        if (entity_type, _normalise(entity_type, text)) in self._keys:
            return True
        if entity_type == "DATE" and (birth := parse_birth_date(text)) and birth.dates & self._births:
            return True
        if self._detector is None:
            self._detector = KnownValueDetector(values=values_to_look_for(self._pairs))
        return bool(self._detector.detect(text))


_NOT_FOUND = "nothing: this word was not found"


class _Found:
    """One value that is replaced, and where."""

    def __init__(self, entity_type: str, value: str):
        self.type, self.value = entity_type, value
        self.count = 0
        self.kept = 0
        self.already = 0  # an added word that the data had already established: replaced, but not counted here
        self.results: set[str] = set()  # for a birth date: what the cell became
        self.files: set[str] = set()
        self.sources: set[str] = set()
        self.places: Counter[tuple] = Counter()  # (file, table, column) -> how often, for cells of table rows
        self.loose: Counter[str] = Counter()  # file -> how often anywhere else in it


class Anonymizer(Transformer):
    def __init__(
        self,
        pseudonymizer: Pseudonymizer,
        detectors: list[Detector],
        link_by_name: bool = False,
        plan=None,
        decisions: Decisions | None = None,
        ai_cache: dict | None = None,
        review: Review | None = None,
    ):
        super().__init__()
        self.columns = ColumnValues()
        self.terms = clean_terms(review.extra) if review is not None else []
        self._keep: set[str] = set(review.keep) if review is not None else set()
        self._known: KnownValueDetector | None = None
        self._found: dict[tuple[str, str], _Found] = {}  # in the files that were read to the end
        self._found_here: list[tuple] = []  # in the file being read
        self._place: tuple | None = None  # (file, table, column) of the cell being read, inside table rows only
        self.seen_columns: dict[tuple[str, str], list[Column]] = {}  # (file, table) -> its columns, as they are treated
        self.done_files: list[str] = []
        self._origin: dict[tuple[str, str], set[str]] = {}  # what found a value first
        self._ids: dict[tuple[str, str], str] = {}
        self.plan = plan
        self.level = plan.level if plan is not None else LEVELS[1]
        self.decisions = decisions or Decisions()
        self.keeps_comments = self.level.keeps_free_text
        self.unchecked: list[str] = []
        self.pseudo = pseudonymizer
        self.base_detectors = list(detectors)
        self.detectors = list(detectors)
        self.link_by_name = link_by_name
        self.registry = Registry(pseudonymizer, link_by_name, self.decisions)
        self._table = ""
        self._row_number = 0
        self._profiles: dict[tuple, _Profile] = {}
        # What the user says a column is counts for any column, whatever its header or values look like.
        self._column_actions: dict[tuple, str] = {
            key: answer for key, answer in self.decisions.columns.items() if answer in ("PERSON", "ID")
        }
        self._keep_dates = False
        self._ai_seen: dict[tuple, list] = {} if ai_cache is None else ai_cache
        self._has_ai = any(d.name in _AI_SOURCES for d in detectors)
        self._ai_off = False  # inside a table cell the AI is not asked about
        self._ai_findings: set[str] = set()  # words only the AI thinks are names or organisations
        self._no_ai_findings = False  # category cells and labels: only what rules and tables established
        self.kept_date_columns: set[str] = set()
        self._date_values: dict[tuple, dict[int, dt.date]] = {}
        self._birth_columns: set[tuple] = set()
        self._ages: dict[tuple, dict[int, float]] = {}  # (file, table) -> row -> age
        self._column_names: dict[tuple, str] = {}
        self.collecting = True  # first pass: only gather evidence about who is who
        self.current_file = ""
        self._chunks: list[tuple[str, str, list[Span]]] = []
        self._row_person: Person | None = None

    def finish_collecting(self) -> None:
        """After the first pass: decide who is who, then also replace every value seen anywhere."""
        self._judge_columns()
        self._check_birth_date_columns()
        self._ask_ai_about_free_text_columns()
        self.registry.resolve_records()
        self._find_known_people_in_text()
        self.registry.resolve_mentions()
        self._ai_findings -= self.registry.established_words()
        self._chunks = []
        self.collecting = False
        self._known = KnownValueDetector(self.pseudo, self.terms)
        self.detectors = self.base_detectors + [self._known]

    # -- what is replaced, for the review screen -----------------------------------
    def reset_file_stats(self) -> None:
        super().reset_file_stats()
        self._found_here = []

    def _note_found(self, key: tuple[str, str], value: str, source: str, kept: bool = False, result=None) -> None:
        if not self.collecting:
            self._found_here.append((key, value, source, kept, result, self._place))

    def file_done(self) -> None:
        """The file was read to the end, so what was found in it counts."""
        self.done_files.append(self.current_file)
        for key, value, source, kept, result, place in self._found_here:
            found = self._found.get(key)
            if found is None:
                found = self._found[key] = _Found(key[0], value)
            if source == "already":
                found.already += 1
                continue
            found.count += 1
            found.kept += kept
            if result is not None:
                found.results.add(str(result))
            found.files.add(self.current_file)
            found.sources.add(source)
            if place is not None:
                found.places[place] += 1
            else:
                found.loose[self.current_file] += 1
        self._found_here = []

    def _id(self, key: tuple[str, str]) -> str:
        if key not in self._ids:
            self._ids[key] = id_of_key(key)
        return self._ids[key]

    def _span_key(self, span: Span) -> tuple[str, str]:
        if span.entity_type == "TERM" and self._known is not None and (term := self._known.term_of(span.text)):
            return finding_key("TERM", term)
        return finding_key(span.entity_type, span.text)

    def _kept(self, key: tuple[str, str]) -> bool:
        """The user ticked this value to stay as written. That holds wherever it occurs, also in an identifying column."""
        return bool(self._keep) and key[0] != "TERM" and self._id(key) in self._keep

    def _left_as_written(self, span: Span, key: tuple[str, str]) -> bool:
        return self._kept(key)

    @property
    def kept_values(self) -> int:
        return sum(1 for found in self._found.values() if found.kept)

    @property
    def kept_places(self) -> int:
        return sum(found.kept for found in self._found.values())

    @property
    def added_places(self) -> int:
        return sum(found.count for found in self._found.values() if found.type == "TERM")

    @property
    def added_found(self) -> int:
        return sum(1 for found in self._found.values() if found.type == "TERM" and (found.count or found.already))

    def findings(self) -> list[Finding]:
        """One entry per value. Holds real values: for the user's screen only."""
        out = []
        for key, found in self._found.items():
            sources = found.sources | self._origin.get(key, set())
            if found.type == "TERM":
                source = "added"
            elif "column" in sources or self.columns.holds(found.type, found.value):
                source = "column"
            elif "pattern" in sources:
                source = "rule"
            elif sources & _AI_SOURCES:
                source = "ai"
            else:
                source = "known"
            out.append(
                Finding(
                    self._id(key), found.type, found.value, found.count, sorted(found.files), source,
                    source != "added", bool(found.kept), found.already, self._becomes(found),
                )
            )
        for term in self.terms:  # a word that occurs nowhere is listed too, so that the user sees it was looked for
            key = finding_key("TERM", term)
            if key not in self._found:
                out.append(Finding(self._id(key), "TERM", term, 0, [], "added", False, becomes=_NOT_FOUND))
        return sorted(out, key=lambda f: (f.type, f.value.casefold(), f.id))

    def column_kind(self, ref: tuple, column: Column, seen_as: str | None, has_findings: bool) -> tuple[str, str]:
        """What a table column is treated as, and what it becomes at level 1. `seen_as` is how the check reads it."""
        action = self._column_actions.get(ref)
        if column.keep:
            return "PLAIN", "stays as it is, as you decided"
        if action in ("PERSON", "ID", "DATE"):
            return action, code_in_words(action)
        if column.category == "DOB":
            return "BIRTH_DATE", "the year only"
        if column.category == "BIRTH_YEAR":
            return "BIRTH_YEAR", "stays as it is"
        if column.category in CATEGORY_TO_TYPE:
            return CATEGORY_TO_TYPE[column.category], code_in_words(CATEGORY_TO_TYPE[column.category])
        if action == "KEEP_DATES" or column.dates:
            return "DATE", "dates stay as they are, with day and month"
        if column.role == "gender" or seen_as == "sex":
            return "SEX", "stays as it is"
        profile = self._profiles.get(ref)
        if has_findings or (profile is not None and profile.words and self._column_is_free_text(ref)):
            return "TEXT", "names, dates and the like inside are replaced"
        if seen_as == "age":
            return "AGE", "stays as it is"
        return "PLAIN", "stays as it is"

    def found_by_place(self) -> tuple[dict[tuple, list], dict[str, list]]:
        """(column -> its findings) and (file -> what is found outside table columns), each as (finding, how often)."""
        in_columns: dict[tuple, list] = {}
        loose: dict[str, list] = {}
        for key, found in self._found.items():
            for place, count in found.places.items():
                in_columns.setdefault(place, []).append((key, found, count))
            for file, count in found.loose.items():
                loose.setdefault(file, []).append((key, found, count))
        return in_columns, loose

    def finding_id_of(self, key: tuple[str, str]) -> str:
        return self._id(key)

    @staticmethod
    def _becomes(found: _Found) -> str:
        """What the value turns into at level 1. Says only what is certain."""
        if found.kept:
            return "kept as written"
        if found.type == "BIRTH_DATE":
            if len(found.results) == 1:
                return f"the year {next(iter(found.results))}"
            return "the year only"
        if found.type == "TERM" and not found.count:
            return "already replaced, as another finding" if found.already else _NOT_FOUND
        return code_in_words(found.type)

    def begin_table(self, name: str) -> None:
        self._table = name
        self._row_number = 0

    def identifies(self, index: int, column: Column) -> bool:
        action = self._column_actions.get((self.current_file, self._table, index))
        return (
            super().identifies(index, column)
            or action in ("PERSON", "ID", "DATE")
            or self.reduced_column(index)
            or self.blanks_in_column(index)
        )

    def reduced_column(self, index: int) -> bool:
        return self.plan is not None and self.plan.action(self.current_file, self._table, index) is not None

    def blanks_in_column(self, index: int) -> bool:
        if self.plan is None:
            return False
        return any(index in columns for columns in self.plan.blanks.get((self.current_file, self._table), {}).values())

    def table_without_header(self) -> bool:
        return not self.level.keeps_free_text

    def outside_the_rows(self, value):
        if self.level.number >= 3 and is_date_object(value):
            return None
        return value

    def formula_replacement(self, index: int, value, is_date_cell: bool = False):
        """A formula can show the exact age or date again, so only its reduced result stays."""
        if self.plan is None:
            return KEEP_FORMULA
        action = self.plan.action(self.current_file, self._table, index)
        blanked = self.plan.blanked(self.current_file, self._table, self._row_number, index)
        if action is None and not blanked:
            return KEEP_FORMULA
        if blanked:
            return None
        reduced = reduce_value(action, value)
        return None if reduced is UNREAD else reduced

    def _ask_about_column(self, key: tuple, where: str, text: str, options: list[tuple[str, str]]) -> None:
        question = self.registry._ask(f"column|{key}", "column", f"{where}: {text}", options, {key[0]}, key)
        question.columns.add(key)

    def _answered(self, columns: list[Column]) -> list[Column]:
        """What the user said about a column counts more than its header."""
        if not self.decisions.columns:
            return columns
        return [self._answered_one((self.current_file, self._table, i), column) for i, column in enumerate(columns)]

    def _answered_one(self, ref: tuple, column: Column) -> Column:
        answer = self.decisions.columns.get(ref)
        if answer == "DOB":
            return column._replace(category="DOB", dates=False)
        if answer == "KEEP_DATES":
            return column._replace(category=None, dates=True)
        if answer == "KEEP":
            return column._replace(category=None, role=None, dates=False, keep=True)
        if answer in ("PERSON", "ID"):  # coded value by value, see row()
            return column._replace(category=None, role=None, dates=False)
        return column

    def note_removed(self, kind: str, count: int) -> None:
        if not self.collecting:
            self.warnings.append(
                f"{count} {kind}(s) removed from the copy, as they can hold data that cannot be checked. The original keeps them."
            )

    def note_unchecked(self, note: str) -> None:
        if not self.collecting and note not in self.warnings:
            self.warnings.append(f"{note}: please check.")

    def note_withheld_results(self, where: str) -> None:
        note = (
            f"{where}: these formulas use an identifying column, so their stored results were removed. Excel will "
            "recalculate them from the codes, which may give errors. Please check."
        )
        if not self.collecting and note not in self.warnings:
            self.warnings.append(note)

    def _judge_columns(self) -> None:
        """Columns the header says nothing about are judged by their values. Nothing is assumed:
        without a header a column that may identify someone is replaced, which can be undone,
        and Privatier asks. With a header it stays as it is, and Privatier asks."""
        for key, p in self._profiles.items():
            if p.filled < _MIN_VALUES:
                continue
            named = bool(p.column.key)
            where = f"{p.label}"
            answer = self.decisions.columns.get(key)
            if answer in ("KEEP_DATES", "PERSON", "ID"):
                self._column_actions[key] = answer
                if answer == "KEEP_DATES" and self.level.number == 1:
                    self.kept_date_columns.add(where)
            elif answer in ("DOB", "KEEP"):
                pass
            elif p.share(p.dates) >= _MOST:
                if named:
                    self._column_actions[key] = "KEEP_DATES"
                    if self.level.number == 1:
                        self.kept_date_columns.add(where)
                else:
                    self._column_actions[key] = "DATE"
                    self.registry.review.append(
                        f"{where} has no header and holds dates. It could be a birth date, so it was replaced: "
                        "please say what it is."
                    )
                    self._ask_about_column(
                        key, where, "this column has no header and holds dates. What are they?",
                        [("DOB", "Birth dates"), ("KEEP_DATES", "Other dates"), ("UNSURE", "Not sure, keep them coded")],
                    )
            elif p.share(p.names) >= _ALMOST_ALL and p.varied >= _MOST:
                if named:
                    self.registry.review.append(f"{where}: the values look like names. Left unchanged, please check.")
                    self._ask_about_column(
                        key, where, "the values look like names, so far they stay unchanged. Are they names of people?",
                        [("PERSON", "Yes, replace them"), ("KEEP", "No, keep them")],
                    )
                else:
                    self._column_actions[key] = "PERSON"
                    self.registry.review.append(
                        f"{where} has no header and the values look like names, so it was replaced: please confirm."
                    )
                    self._ask_about_column(
                        key, where, "this column has no header and the values look like names, so they were replaced. Are they names of people?",
                        [("PERSON", "Yes, replace them"), ("KEEP", "No, keep them")],
                    )
            elif not named and p.share(p.whole) >= _ALMOST_ALL and p.varied >= 0.9:
                self._column_actions[key] = "ID"
                self.registry.review.append(
                    f"{where} has no header and holds a different number in almost every row. It could be an ID, "
                    "so it was replaced: please say what it is."
                )
                self._ask_about_column(
                    key, where, "this column has no header and holds a different number in almost every row. Is it an ID?",
                    [("ID", "Yes, an ID: replace it"), ("KEEP", "No, a measurement: keep it")],
                )
        for key, action in self._column_actions.items():
            profile = self._profiles.get(key)
            if profile is None:
                continue
            if action == "PERSON":
                for value in sorted(profile.values):
                    if not self._kept(finding_key("PERSON", value.strip())):
                        self.pseudo.token_for("PERSON", value.strip())  # also looked for everywhere else
            if action in ("PERSON", "ID", "DATE"):
                for value in profile.texts | profile.values:
                    self.columns.add(action, value)

    def _check_birth_date_columns(self) -> None:
        for key in sorted(self._birth_columns):
            file, table, _ = key
            others = {
                self._column_names[k]: values
                for k, values in self._date_values.items()
                if k[0] == file and k != key
            }
            same_table = {self._column_names[k] for k in self._date_values if k[:2] == (file, table) and k != key}
            problems = check_birth_date_column(
                self._date_values.get(key, {}), others, same_table, self._ages.get((file, table), {})
            )
            if problems:
                if key in self.decisions.columns:
                    continue
                self.registry.review.append(
                    f"{file}, {self._column_names[key]} is called a birth date, but {'; '.join(problems)}. It was "
                    "treated as a birth date (year only). If that is wrong, correct the header and run again."
                )
                self._ask_about_column(
                    key, f"{file}, {self._column_names[key]}",
                    f"this column is called a birth date, but {'; '.join(problems)}. What does it hold?",
                    [("DOB", "Birth dates"), ("KEEP_DATES", "Other dates")],
                )

    def _column_is_free_text(self, key: tuple) -> bool:
        """A column that repeats a few values holds categories ("Placebo", "T0"), not sentences about people."""
        p = self._profiles.get(key)
        if p is None or self._column_actions.get(key) in ("PERSON", "ID", "DATE"):
            return False
        return len(p.values) > _MAX_CATEGORIES or p.varied >= _MOST

    def _ai_may_read(self, key: tuple, value) -> bool:
        return (
            isinstance(value, str)
            and not self._column_actions.get(key) == "KEEP_DATES"
            and self._column_is_free_text(key)
            and len(value.split()) >= _MIN_WORDS_FOR_AI
        )

    def _ask_ai_about_free_text_columns(self) -> None:
        if not any(d.name in _AI_SOURCES for d in self.base_detectors):
            return
        for key, profile in self._profiles.items():
            self.current_file, self._table, _ = key
            for value in sorted(profile.values):
                if self._ai_may_read(key, value):
                    self.text(value)
        self._table = ""

    def _find_known_people_in_text(self) -> None:
        """A letter about Hannah Berger may only name her in a way that needs the tables to be recognised.

        Without this her mother, named by a rule, would look like the only Berger in the letter.
        """
        known = KnownValueDetector(self.pseudo)
        for file, value, spans in self._chunks:
            for span in known.detect(value):
                if span.entity_type != "PERSON" or len(name_parts(span.text)) < 2:
                    continue
                if any(s.start < span.end and span.start < s.end and s.entity_type == "PERSON" for s in spans):
                    continue
                if self._left_as_written(span, self._span_key(span)):
                    continue
                gender, academic = _title_before(value, span)
                birth = _birth_date_next_to(value, span, [*spans, span])
                self.registry.observe_mention(
                    file, span.text, gender, academic, birth, relative=_is_relative(value, span)
                )

    @property
    def detector_names(self) -> list[str]:
        return [d.name for d in self.detectors]

    def header(self, value: str) -> str:
        # Headers and labels are short and context-free: the AI guesses badly there
        # ("Geschlecht" as a person), so only rules and known values apply.
        self._no_ai_findings = True
        try:
            return self.text(value, use_ai=False)
        finally:
            self._no_ai_findings = False

    def text(self, value: str, use_ai: bool = True) -> str:
        if not value or not any(c.isalnum() for c in value):
            return value
        spans = []
        for detector in self.detectors:
            if detector.name in _AI_SOURCES and (not use_ai or self._ai_off):
                continue
            spans.extend(self._detect(detector, value))
        if self._keep_dates:
            spans = [s for s in spans if s.entity_type != "DATE"]
        spans = [_only_the_name(value, s) for s in spans]
        if self._no_ai_findings:
            spans = [
                s for s in spans
                if not (s.source == "known" and s.entity_type != "TERM" and _plain(s.text) in self._ai_findings)
            ]
        if self.collecting:
            for s in spans:
                if s.source in _AI_SOURCES:
                    self._ai_findings.add(_plain(s.text))
                    self._ai_findings.update(_plain(word) for word in s.text.split())
        spans = [
            s
            for s in spans
            if not TOKEN_RE.fullmatch(s.text) and not _ai_false_alarm(s) and not _ordinary_word(value, s)
        ]
        if not self.collecting:
            spans = [_with_given_name(value, s) for s in spans]
        chosen = resolve_overlaps(spans)
        keys = [self._span_key(s) for s in chosen]
        left = {i for i, s in enumerate(chosen) if self._left_as_written(s, keys[i])} if self._keep else set()
        if self.collecting:
            for span, key in zip(chosen, keys):
                self._origin.setdefault(key, set()).add(span.source)
            self._collect_from_text(value, chosen, left)
            self._chunks.append((self.current_file, value, chosen))
        out, last = [], 0
        for i, span in enumerate(chosen):
            if i in left:  # stays exactly as written, and gets no code
                self._note_found(keys[i], span.text, span.source, kept=True)
                continue
            token = self._token_for_span(value, span, chosen)
            shown = span.text
            if span.entity_type == "TERM" and self._known is not None:
                shown = self._known.term_of(span.text) or span.text  # the word as the user typed it
            self._note_found(keys[i], shown, span.source)
            if self.terms and span.entity_type != "TERM" and self._known is not None:
                if term := self._known.term_of(span.text):  # replaced anyway, under the type the data gave it
                    self._note_found(finding_key("TERM", term), term, "already")
            out.append(value[last : span.start])
            out.append(token)
            last = span.end
            self.stats[span.entity_type] += 1
            self.tokens.add(token)
        out.append(value[last:])
        return "".join(out)

    def _detect(self, detector: Detector, text: str) -> list[Span]:
        if detector.name not in _AI_SOURCES:
            return detector.detect(text)
        # Tables repeat the same values, and the model is slow. "1,2" or "ok" holds no name.
        if not _WORTH_ASKING_AI.search(text):
            return []
        known = self._ai_seen.get((detector.name, text))
        if known is None:
            known = detector.detect(text)
            self._ai_seen[(detector.name, text)] = known
        return known

    # -- free text ---------------------------------------------------------------
    def _token_for_span(self, value: str, span: Span, spans: list[Span]) -> str:
        if span.entity_type == "TERM":
            term = (self._known.term_of(span.text) if self._known is not None else None) or span.text
            return self.pseudo.form_of(self.pseudo.base_for("TERM", term), span.text)
        if span.entity_type != "PERSON":
            one_word = " " not in span.text.strip()
            if self.collecting and span.source in _AI_SOURCES and one_word and span.entity_type != "LOCATION":
                return span.text  # a single AI guess must not spread to every other file
            return self.pseudo.token_for(span.entity_type, span.text)
        if self.collecting:
            return span.text  # who this is gets decided once all files were read
        gender, academic = _title_before(value, span)
        birth = _birth_date_next_to(value, span, spans)
        person, note = self.registry.person_for_mention(
            span.text, self.current_file, gender, academic, birth, self._row_person, self._place
        )
        if note and note not in self.warnings:
            self.warnings.append(note)
        if person is None:
            return self.pseudo.token_for("PERSON", span.text)
        return self.pseudo.form_of(person.token, span.text, self.registry.form_for(person, span.text))

    def _collect_from_text(self, value: str, spans: list[Span], left: set[int] = frozenset()) -> None:
        evidence = self.registry.file(self.current_file)
        for i, span in enumerate(spans):
            if i in left and span.entity_type == "PERSON":
                continue  # the user said this is no name: it is nobody, and nothing is asked about it
            if span.entity_type == "ID":
                evidence.ids.add(span.text.strip())
            elif span.entity_type == "DATE" and _BIRTH_MARK.search(value[max(0, span.start - 25) : span.start]):
                birth = parse_birth_date(span.text)
                if birth:
                    evidence.birth_dates.append(birth)
            elif span.entity_type == "PERSON":
                gender, academic = _title_before(value, span)
                birth = _birth_date_next_to(value, span, spans)
                self.registry.observe_mention(
                    self.current_file, span.text, gender, academic, birth, span.source in _AI_SOURCES,
                    _is_relative(value, span),
                )

    # -- tables ------------------------------------------------------------------
    def classify(self, header: str | None, label: str | None = None) -> str | None:
        return classify_header(header, label)

    def _record_of_row(self, columns: list[Column], values: list) -> Record | None:
        first, last, full, birth, gender = None, None, None, None, None
        ids: set[tuple[str, str]] = set()
        name_columns: set[tuple] = set()
        birth_columns: set[tuple] = set()
        for i, value in enumerate(values):
            column = _column_at(columns, i)
            if _blank(value):
                continue
            text = _cell_text(value).strip()
            if TOKEN_RE.fullmatch(text):
                continue  # already anonymised
            if column.category == "PERSON" and column.role in _NAME_ROLES:
                name_columns.add((self.current_file, self._table, i))
                if column.role == "first":
                    first = text
                elif column.role == "last":
                    last = text
                else:
                    full = text
            elif column.category in ("DOB", "BIRTH_YEAR"):
                if birth is None and (birth := parse_birth_date(value)) is not None:
                    birth_columns.add((self.current_file, self._table, i))
            elif column.category == "ID" and not column.visit_id:
                ids.add((column.key, text))
            elif column.role == "gender":
                gender = _GENDER_WORDS.get(text.casefold())
        if full and not (first or last) and (split := surname_first(full)):
            first, last = split
        canonical = full or " ".join(p for p in (first, last) if p)
        if not canonical:
            return None
        spellings = {s for s in (canonical, first, last) if s}
        row = None if self.link_by_name else (self.current_file, self._table, self._row_number)
        return Record(
            name_key(canonical), " ".join(canonical.split()), first, last, birth, frozenset(ids), gender, set(),
            spellings, row, name_columns, birth_columns,
        )

    def row(self, columns: list[Column], values: list) -> list:
        if _is_legend_row(values):  # "(dd/mm/yyyy)", "(0=no,1=yes)": explains the columns, holds no data
            return [self.header(v) if isinstance(v, str) else v for v in values]
        self._row_number += 1
        columns = _with_name_roles(self._answered(columns))
        if self.collecting:
            self._profile_row(columns, values)
        else:
            self.seen_columns[(self.current_file, self._table)] = columns
        record = self._record_of_row(columns, values)
        person: Person | None = None
        if record is not None:
            if self.collecting:
                self.registry.observe_record(record, self.current_file)
            else:
                person = self.registry.person_for_record(record)
        out = []
        self._row_person = person
        for i, value in enumerate(values):
            column = _column_at(columns, i)
            action = self._column_actions.get((self.current_file, self._table, i))
            if self.plan is not None and not self.collecting and not _blank(value):
                reduced = self._reduced(i, value, column)
                if reduced is not UNREAD:
                    out.append(reduced)
                    continue
            if column.keep:  # the user's decision for the whole column: nothing is looked for in it
                out.append(value)
                continue
            self._place = (self.current_file, self._table, i)
            if column.category == "PERSON" and column.role in _NAME_ROLES and not _blank(value):
                out.append(self._person_cell(column, value, person))
            elif action in ("PERSON", "ID", "DATE") and not _blank(value):
                text = _cell_text(value).strip()
                self.columns.add(action, text)
                if TOKEN_RE.fullmatch(text):
                    out.append(value)
                elif self._kept(finding_key(action, text)):
                    self._note_found(finding_key(action, text), text, "column", kept=True)
                    out.append(value)
                else:
                    token = self.pseudo.token_for(action, text)
                    self._note_found(finding_key(action, text), text, "column")
                    self.stats[action] += 1
                    self.tokens.add(token)
                    out.append(token)
            else:
                # Above level 1 no exact date stays: one that could not be reduced becomes a code.
                self._keep_dates = self.level.number == 1 and (
                    action == "KEEP_DATES" or (column.category is None and column.dates)
                )
                # In the first pass the AI waits until the whole column was seen.
                column_key_ = (self.current_file, self._table, i)
                self._ai_off = self.collecting or not self._ai_may_read(column_key_, value)
                self._no_ai_findings = not self.collecting and not self._column_is_free_text(column_key_)
                new = self.cell(column.category, value)
                self._no_ai_findings = False
                if not self._ai_off and not self.collecting and new != value and self._has_ai:
                    note = f"the AI changed free text in column {_letters(i)}{' of ' + self._table if self._table else ''}, please check."
                    if note not in self.warnings:
                        self.warnings.append(note)
                out.append(new)
                self._keep_dates = self._ai_off = False
        self._row_person = None
        self._place = None
        return out

    def _reduced(self, index: int, value, column: Column):
        """What a level does to this cell. UNREAD if nothing, and the cell goes the usual way."""
        file, table = self.current_file, self._table
        if self.plan.blanked(file, table, self._row_number, index):
            self.stats["BLANKED_RARE"] += 1
            return None
        action = self.plan.action(file, table, index)
        if action is None and column.category is None and is_date_object(value):
            action = self.level.dates  # a stray date in a column that holds other things
        if action is None:
            return UNREAD
        reduced = reduce_value(action, value)
        if reduced is UNREAD:
            return UNREAD
        self.stats[f"REDUCED_{action.upper()}"] += 1
        return reduced

    def _note_for_birth_check(self, key: tuple, column: Column, value) -> None:
        if column.category == "DOB":
            self._birth_columns.add(key)
        elif _AGE_HEADER.search(column.key) and isinstance(value, (int, float)):
            self._ages.setdefault(key[:2], {})[self._row_number] = float(value)
            return
        date = _single_date(value)
        if date is not None:
            self._date_values.setdefault(key, {})[self._row_number] = date
            table = f"{key[1]}, " if key[1] else ""
            self._column_names[key] = f"{table}column {_letters(key[2])}"

    def _profile_row(self, columns: list[Column], values: list) -> None:
        for i, value in enumerate(values):
            column = _column_at(columns, i)
            if _blank(value):
                continue
            key = (self.current_file, self._table, i)
            self._note_for_birth_check(key, column, value)
            if column.category is None and column.dates and self.level.number == 1:
                self.kept_date_columns.add(
                    f"{self.current_file}, {self._table + ', ' if self._table else ''}column {_letters(i)}"
                )
            if column.category is not None or column.role == "gender":
                continue
            if column.keep:
                continue
            profile = self._profiles.get(key)
            if profile is None:
                label = f"{self.current_file}, {self._table + ', ' if self._table else ''}column {_letters(i)}"
                profile = self._profiles[key] = _Profile(column, label)
            profile.add(value)

    def labelled(self, category: str, value: str):
        if value.strip():  # the label makes it a value of an identifying column, whatever else finds it
            if category == "DOB":
                self.columns.add_birth(value.strip())
            elif category in CATEGORY_TO_TYPE:
                self.columns.add(CATEGORY_TO_TYPE[category], value.strip())
        new = self.text(value)
        if new != value or not value.strip():
            return new
        if category == "PERSON":  # same path as any other name, so that it links to the same person
            span = Span(0, len(value), "PERSON", value.strip(), "pattern")
            if self.collecting:
                if not self._kept(finding_key("PERSON", span.text)):
                    self.registry.observe_mention(self.current_file, span.text, None, False, None)
                return value
            if self._kept(finding_key("PERSON", span.text)):
                self._note_found(finding_key("PERSON", span.text), span.text, "column", kept=True)
                return value
            token = self._token_for_span(value, span, [span])
            self._note_found(finding_key("PERSON", span.text), span.text, "column")
            return token
        evidence = self.registry.file(self.current_file)
        if self.collecting and category == "DOB" and (birth := parse_birth_date(value)):
            evidence.birth_dates.append(birth)
        if self.collecting and category == "ID":
            evidence.ids.add(value.strip())
        return str(self.cell(category, value))

    def _person_cell(self, column: Column, value, person: Person | None):
        text = _cell_text(value).strip()
        if TOKEN_RE.fullmatch(text):
            return text
        self.columns.add("PERSON", text)
        if self._kept(finding_key("PERSON", text)):  # the row still tells who it is about, the cell stays
            self._note_found(finding_key("PERSON", text), text, "column", kept=True)
            return value
        if self.collecting:
            return text
        if person is None:  # e.g. a name without a usable key
            return self.cell(column.category, value)
        form = {"first": "F", "last": "L"}.get(column.role, "V")
        token = self.pseudo.form_of(person.token, text, form)
        self._note_found(finding_key("PERSON", text), text, "column")
        self.stats["PERSON"] += 1
        self.tokens.add(token)
        return token

    def cell(self, category: str | None, value):
        if _blank(value):
            return value
        if category == "DOB":
            self.columns.add_birth(value)
            readable = _has_year(value)
            key = finding_key("BIRTH_DATE", _shown(value)) if readable else finding_key("DATE", str(value))
            if self._kept(key):  # the full birth date stays
                self._note_found(key, _shown(value) if readable else " ".join(str(value).split()), "column", kept=True)
                return value
            self.stats["DATE_OF_BIRTH_TO_YEAR"] += 1
            year = _year_of(value, self)
            if not readable:  # not readable as a date, so it became a code
                self.columns.add("DATE", str(value))
                self._note_found(key, " ".join(str(value).split()), "column")
            else:
                self._note_found(key, _shown(value), "column", result=year)
            return year
        if category in CATEGORY_TO_TYPE:
            etype = CATEGORY_TO_TYPE[category]
            text = _cell_text(value)
            if TOKEN_RE.fullmatch(text.strip()):
                return text
            self.columns.add(etype, text.strip())
            if self._kept(finding_key(etype, text.strip())):
                self._note_found(finding_key(etype, text.strip()), text.strip(), "column", kept=True)
                return value
            token = self.pseudo.token_for(etype, text.strip())
            self._note_found(finding_key(etype, text.strip()), text.strip(), "column")
            self.stats[etype] += 1
            self.tokens.add(token)
            return token
        return super().cell(category, value)


def _title_before(value: str, span: Span) -> tuple[str | None, bool]:
    """The gender (Herr/Frau) and doctor's title right before a name, or at the start of it."""
    before = value[max(0, span.start - 30) : span.start]
    # The AI may include the title in the name it found: "Herrn Dr. Jürgen Weiß".
    academic = bool(_ACADEMIC.search(before)) or bool(re.search(r"(?<!\w)(Dr\.|Prof\.|PD)(?!\w)", span.text))
    m = _BEFORE_NAME.search(before)
    word = (m.group(1) if m else None) or span.text.split(" ")[0]
    return _GENDER_WORDS.get(word.strip(".").casefold()), academic


def _is_relative(value: str, span: Span) -> bool:
    return bool(_RELATIVE_BEFORE.search(value[max(0, span.start - 25) : span.start]))


def _with_given_name(value: str, span: Span) -> Span:
    """"Ben Berger" when only Berger is known: the word in front of a known surname goes with it."""
    if span.source != "known" or span.entity_type != "PERSON" or " " in span.text.strip():
        return span
    m = _WORD_BEFORE.search(value[max(0, span.start - 30) : span.start])
    if m is None or m.group(1) in _NOT_NAMES or is_stopword(m.group(1)):
        return span
    start = span.start - len(m.group(0).lstrip())
    return Span(start, span.end, span.entity_type, value[start : span.end], span.source, span.score)


def _birth_date_next_to(value: str, span: Span, spans: list[Span]):
    """"Max Müller, geb. 12.05.1975": the birth date that belongs to this mention of a name."""
    if m := _BIRTH_YEAR_AFTER.match(value[span.end : span.end + 25]):
        return parse_birth_date(m.group(1))
    for other in spans:
        if other.entity_type != "DATE" or other.start < span.end or other.start - span.end > _NEAR:
            continue
        between = value[span.end : other.start]
        if "\n" in between or any(s.entity_type == "PERSON" and span.end <= s.start < other.start for s in spans):
            return None
        if _ONLY_SEPARATORS.match(between) or _BIRTH_MARK.search(between):
            return parse_birth_date(other.text)
        return None
    return None


_AI_SOURCES = {"ner", "llm"}


def _ai_false_alarm(span) -> bool:
    """AI findings that are common research words or have no capital letter are ignored."""
    if span.source not in _AI_SOURCES:
        return False
    text = span.text.strip()
    if len(text) <= 2 or (text.isupper() and len(text) <= 4):
        return True  # abbreviations, not names ("RS", "ICD")
    return is_stopword(text) or not any(c.isupper() for c in text)


def _only_the_name(value: str, span: Span) -> Span:
    """The AI may return "Gutachten vdBerg" or two lines at once: keep only what can be the name."""
    if span.source not in _AI_SOURCES or span.entity_type != "PERSON":
        return span
    start, end = span.start, span.end
    if "\n" in value[start:end]:
        end = start + value[start:end].index("\n")
    words = list(re.finditer(r"\S+", value[start:end]))
    while len(words) > 1 and is_stopword(words[0].group()):
        words.pop(0)
    while len(words) > 1 and is_stopword(words[-1].group()):
        words.pop()
    if not words:
        return span
    begin, finish = start + words[0].start(), start + words[-1].end()
    return Span(begin, finish, span.entity_type, value[begin:finish], span.source, span.score)


def _ordinary_word(value: str, span: Span) -> bool:
    if span.entity_type != "PERSON" or " " in span.text.strip():
        return False
    return is_ordinary_use(span.text.strip(), value[max(0, span.start - 20) : span.start], value[span.end : span.end + 20])


def _has_year(value) -> bool:
    """Whether _year_of can read a year, or has to replace the whole value."""
    return isinstance(value, (dt.date, dt.datetime)) or hasattr(value, "year") or bool(
        re.search(r"\b(19|20)\d{2}\b", str(value))
    )


def _year_of(value, anon: Anonymizer):
    """Birth dates are reduced to the year: still useful for age, far less identifying.

    The full date is kept in the encrypted key file, see identity.py.
    """
    if isinstance(value, (dt.date, dt.datetime)):
        return value.year
    if hasattr(value, "year"):  # pandas Timestamp
        return int(value.year)
    m = re.search(r"\b(19|20)\d{2}\b", str(value))
    if m:
        return int(m.group(0))
    # Unknown format: don't guess, replace completely.
    token = anon.pseudo.token_for("DATE", str(value))
    anon.tokens.add(token)
    return token


class Restorer(Transformer):
    def __init__(self, pseudonymizer: Pseudonymizer):
        super().__init__()
        self.pseudo = pseudonymizer
        self.unknown: Counter[str] = Counter()
        self._births = {p["token"]: p["births"] for p in pseudonymizer.people}

    def text(self, value: str) -> str:
        def repl(m: re.Match[str]) -> str:
            base = f"{m.group(1).upper()}_{m.group(2)}"
            suffix = m.group(3)
            token = f"{base}_{suffix.upper()}" if suffix else base
            original = self.pseudo.original(token)
            if original is None and suffix and self.pseudo.original(base) is not None:
                # "PERSON_0001_A" that Privatier never wrote: the base is real, the rest stays.
                self.stats[m.group(1).upper()] += 1
                return self.pseudo.original(base) + m.group(0)[len(base) :]
            if original is None:
                self.unknown[token] += 1
                return m.group(0)
            self.stats[m.group(1).upper()] += 1
            self.tokens.add(token)
            return original

        if not value:
            return value
        restored = TOKEN_RE.sub(repl, value)

        def glued(m: re.Match[str]) -> str:
            original = self.pseudo.original(f"{m.group(1)}_{m.group(2)}")
            return m.group(0) if original is None else original

        return GLUED_TOKEN_RE.sub(glued, restored)

    def classify(self, header: str | None, label: str | None = None) -> str | None:
        return classify_header(header, label)

    def row(self, columns: list[Column], values: list) -> list:
        """Birth dates became years. If the row names its person, the full date can come back."""
        births = self._births_in_row(values)
        out = []
        for i, value in enumerate(values):
            if _column_at(columns, i).category == "DOB" and not _blank(value):
                out.append(_restored_birth_date(value, births))
            else:
                out.append(Transformer.cell(self, None, value))
        return out

    def _births_in_row(self, values: list) -> list[dict]:
        people: set[str] = set()
        for value in values:
            if isinstance(value, str):
                for m in TOKEN_RE.finditer(value):
                    people.add(f"{m.group(1).upper()}_{m.group(2)}")
        return [b for token in people for b in self._births.get(token, [])]


def _restored_birth_date(value, births: list[dict]):
    """Only certain if exactly one known birth date of this person fits the year in the cell."""
    year = _cell_text(value).strip()
    fitting = [b for b in births if str(b["year"]) == year or any(d.startswith(year) for d in b["dates"])]
    return fitting[0]["raw"] if len(fitting) == 1 else value
