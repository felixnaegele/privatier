"""The two directions of Privatier: anonymise (real -> token) and restore (token -> real).

File handlers don't care which direction they run in. They hand text, table
headers and table rows to a Transformer and write back whatever it returns.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from typing import NamedTuple

from .detect.base import Detector, Span, resolve_overlaps
from .detect.patterns import _NOT_NAMES, NAME_SEQ, NAME_WORD
from .detect.stopwords import is_ordinary_use, is_stopword
from .identity import Person, Record, Registry, name_key, name_parts, parse_birth_date, surname_first
from .pseudonyms import TOKEN_RE, KnownValueDetector, Pseudonymizer
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


_DATE_IN_TEXT = re.compile(r"^\s*\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|^\s*\d{4}-\d{2}-\d{2}")
_LEGEND = re.compile(r"^\s*\(.*\)\s*$|^\s*\d+\s*=|=\s*\d|^\s*\[.*\]\s*$")
_MAX_CATEGORIES = 20
_MIN_WORDS_FOR_AI = 2
_ALMOST_ALL = 0.8
_MOST = 0.5
_MIN_VALUES = 5


class _Profile:
    """What the values of one table column look like, to judge columns the header says nothing about."""

    def __init__(self, column: Column, label: str):
        self.column, self.label = column, label
        self.filled, self.dates, self.names, self.whole = 0, 0, 0, 0
        self.values: set[str] = set()

    def add(self, value) -> None:
        self.filled += 1
        self.values.add(str(value))
        if hasattr(value, "year"):
            self.dates += 1
        elif isinstance(value, str):
            self.dates += bool(_DATE_IN_TEXT.match(value))
            self.names += bool(_LOOKS_LIKE_NAME.fullmatch(value.strip())) and not is_stopword(value)
        elif isinstance(value, (int, float)) and float(value).is_integer():
            self.whole += 1

    def share(self, count: int) -> float:
        return count / self.filled if self.filled else 0.0

    @property
    def varied(self) -> float:
        return self.share(len(self.values))


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


def _blank(value) -> bool:
    if value is None or (isinstance(value, float) and value != value):
        return True
    if value != value:  # NaT
        return True
    return isinstance(value, str) and not value.strip()


def _cell_text(value) -> str:
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


class Anonymizer(Transformer):
    def __init__(self, pseudonymizer: Pseudonymizer, detectors: list[Detector], link_by_name: bool = False):
        super().__init__()
        self.pseudo = pseudonymizer
        self.base_detectors = list(detectors)
        self.detectors = list(detectors)
        self.link_by_name = link_by_name
        self.registry = Registry(pseudonymizer, link_by_name)
        self._table = ""
        self._row_number = 0
        self._profiles: dict[tuple, _Profile] = {}
        self._column_actions: dict[tuple, str] = {}
        self._keep_dates = False
        self._ai_seen: dict[tuple, list] = {}
        self._has_ai = any(d.name in _AI_SOURCES for d in detectors)
        self._ai_off = False  # inside a table cell the AI is not asked about
        self._ai_only_people = False
        self.collecting = True  # first pass: only gather evidence about who is who
        self.current_file = ""
        self._chunks: list[tuple[str, str, list[Span]]] = []
        self._row_person: Person | None = None

    def finish_collecting(self) -> None:
        """After the first pass: decide who is who, then also replace every value seen anywhere."""
        self._judge_columns()
        self._ask_ai_about_free_text_columns()
        self.registry.resolve_records()
        self._find_known_people_in_text()
        self.registry.resolve_mentions()
        self._chunks = []
        self.collecting = False
        self.detectors = self.base_detectors + [KnownValueDetector(self.pseudo)]

    def begin_table(self, name: str) -> None:
        self._table = name
        self._row_number = 0

    def _judge_columns(self) -> None:
        """Columns the header says nothing about are judged by their values. Nothing is assumed:
        without a header a column that may identify someone is replaced, which can be undone,
        and Privatier asks. With a header it stays as it is, and Privatier asks."""
        for key, p in self._profiles.items():
            if p.filled < _MIN_VALUES:
                continue
            named = bool(p.column.key)
            where = f"{p.label}"
            if p.share(p.dates) >= _MOST:
                if named:
                    self._column_actions[key] = "KEEP_DATES"
                else:
                    self._column_actions[key] = "DATE"
                    self.registry.review.append(
                        f"{where} has no header and holds dates. It could be a birth date, so it was replaced: "
                        "please say what it is."
                    )
            elif p.share(p.names) >= _ALMOST_ALL and p.varied >= _MOST:
                if named:
                    self.registry.review.append(f"{where}: the values look like names. Left unchanged, please check.")
                else:
                    self._column_actions[key] = "PERSON"
                    self.registry.review.append(
                        f"{where} has no header and the values look like names, so it was replaced: please confirm."
                    )
            elif not named and p.share(p.whole) >= _ALMOST_ALL and p.varied >= 0.9:
                self._column_actions[key] = "ID"
                self.registry.review.append(
                    f"{where} has no header and holds a different number in almost every row. It could be an ID, "
                    "so it was replaced: please say what it is."
                )
        for key, action in self._column_actions.items():
            if action == "PERSON":
                for value in sorted(self._profiles[key].values):
                    self.pseudo.token_for("PERSON", value.strip())  # also looked for everywhere else

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
            self._ai_only_people = False
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
        return self.text(value, use_ai=False)

    def file_name(self, value: str) -> str:
        # "Verlauf_Berger" reads as two words to a person, so it has to for the detectors too.
        # In the first pass only rules count: the AI guesses badly here, and a guess must not spread.
        self._ai_only_people = True  # "Double Valve" is not an organisation
        try:
            return self.text(value, use_ai=not self.collecting, read_as=value.replace("_", " "))
        finally:
            self._ai_only_people = False

    def text(self, value: str, use_ai: bool = True, read_as: str | None = None) -> str:
        if not value or not any(c.isalnum() for c in value):
            return value
        spans = []
        for detector in self.detectors:
            if detector.name in _AI_SOURCES and (not use_ai or self._ai_off):
                continue
            found = self._detect(detector, read_as if read_as is not None else value)
            if detector.name in _AI_SOURCES and self._ai_only_people:
                found = [s for s in found if s.entity_type == "PERSON"]
            spans.extend(found)
        if self._keep_dates:
            spans = [s for s in spans if s.entity_type != "DATE"]
        spans = [_only_the_name(read_as if read_as is not None else value, s) for s in spans]
        spans = [
            s
            for s in spans
            if not TOKEN_RE.fullmatch(s.text) and not _ai_false_alarm(s) and not _ordinary_word(value, s)
        ]
        if not self.collecting:
            spans = [_with_given_name(value, s) for s in spans]
        chosen = resolve_overlaps(spans)
        if self.collecting:
            self._collect_from_text(value, chosen)
            self._chunks.append((self.current_file, value, chosen))
        out, last = [], 0
        for span in chosen:
            token = self._token_for_span(value, span, chosen)
            written = value[span.start : span.end]
            if written != span.text and not self.collecting:  # "Schulz_Peter", read as "Schulz Peter"
                m = TOKEN_RE.match(token)
                token = self.pseudo.form_of(f"{m.group(1)}_{m.group(2)}", written)
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
            span.text, self.current_file, gender, academic, birth, self._row_person
        )
        if note and note not in self.warnings:
            self.warnings.append(note)
        if person is None:
            return self.pseudo.token_for("PERSON", span.text)
        return self.pseudo.form_of(person.token, span.text, self.registry.form_for(person, span.text))

    def _collect_from_text(self, value: str, spans: list[Span]) -> None:
        evidence = self.registry.file(self.current_file)
        for span in spans:
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
        category = classify_header(header, label)
        if category is None and looks_like_date_column(header, label):
            self.warnings.append(
                f"Column '{header}' looks like it holds dates. Dates other than the birth date are kept "
                "as they are; check whether they could identify someone."
            )
        return category

    def _record_of_row(self, columns: list[Column], values: list) -> Record | None:
        first, last, full, birth, gender = None, None, None, None, None
        ids: set[tuple[str, str]] = set()
        for i, value in enumerate(values):
            column = _column_at(columns, i)
            if _blank(value):
                continue
            text = _cell_text(value).strip()
            if TOKEN_RE.fullmatch(text):
                continue  # already anonymised
            if column.category == "PERSON" and column.role in _NAME_ROLES:
                if column.role == "first":
                    first = text
                elif column.role == "last":
                    last = text
                else:
                    full = text
            elif column.category in ("DOB", "BIRTH_YEAR"):
                birth = birth or parse_birth_date(value)
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
            spellings, row,
        )

    def row(self, columns: list[Column], values: list) -> list:
        if _is_legend_row(values):  # "(dd/mm/yyyy)", "(0=no,1=yes)": explains the columns, holds no data
            return [self.header(v) if isinstance(v, str) else v for v in values]
        self._row_number += 1
        columns = _with_name_roles(columns)
        if self.collecting:
            self._profile_row(columns, values)
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
            if column.category == "PERSON" and column.role in _NAME_ROLES and not _blank(value):
                out.append(self._person_cell(column, value, person))
            elif action in ("PERSON", "ID", "DATE") and not _blank(value):
                token = self.pseudo.token_for(action, _cell_text(value).strip())
                self.stats[action] += 1
                self.tokens.add(token)
                out.append(token)
            else:
                self._keep_dates = action == "KEEP_DATES" or (column.category is None and column.dates)
                # In the first pass the AI waits until the whole column was seen.
                self._ai_off = self.collecting or not self._ai_may_read((self.current_file, self._table, i), value)
                new = self.cell(column.category, value)
                if not self._ai_off and not self.collecting and new != value and self._has_ai:
                    note = f"the AI changed free text in column {_letters(i)}{' of ' + self._table if self._table else ''}, please check."
                    if note not in self.warnings:
                        self.warnings.append(note)
                out.append(new)
                self._keep_dates = self._ai_off = False
        self._row_person = None
        return out

    def _profile_row(self, columns: list[Column], values: list) -> None:
        for i, value in enumerate(values):
            column = _column_at(columns, i)
            if column.category is not None or column.role == "gender" or _blank(value):
                continue
            key = (self.current_file, self._table, i)
            profile = self._profiles.get(key)
            if profile is None:
                label = f"{self.current_file}, {self._table + ', ' if self._table else ''}column {_letters(i)}"
                profile = self._profiles[key] = _Profile(column, label)
            profile.add(value)

    def labelled(self, category: str, value: str):
        new = self.text(value)
        if new != value or not value.strip():
            return new
        if category == "PERSON":  # same path as any other name, so that it links to the same person
            span = Span(0, len(value), "PERSON", value.strip(), "pattern")
            if self.collecting:
                self.registry.observe_mention(self.current_file, span.text, None, False, None)
                return value
            return self._token_for_span(value, span, [span])
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
        if self.collecting:
            return text
        if person is None:  # e.g. a name without a usable key
            return self.cell(column.category, value)
        form = {"first": "F", "last": "L"}.get(column.role, "V")
        token = self.pseudo.form_of(person.token, text, form)
        self.stats["PERSON"] += 1
        self.tokens.add(token)
        return token

    def cell(self, category: str | None, value):
        if _blank(value):
            return value
        if category == "DOB":
            self.stats["DATE_OF_BIRTH_TO_YEAR"] += 1
            return _year_of(value, self)
        if category in CATEGORY_TO_TYPE:
            etype = CATEGORY_TO_TYPE[category]
            text = _cell_text(value)
            if TOKEN_RE.fullmatch(text.strip()):
                return text
            token = self.pseudo.token_for(etype, text.strip())
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

        return TOKEN_RE.sub(repl, value) if value else value

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
