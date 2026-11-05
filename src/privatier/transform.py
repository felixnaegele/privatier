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
from .detect.stopwords import is_stopword
from .identity import Person, Record, Registry, name_key, parse_birth_date
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
    "m": "m", "male": "m", "maennlich": "m", "männlich": "m", "herr": "m", "herrn": "m", "hr": "m", "mr": "m",
    "w": "f", "f": "f", "female": "f", "weiblich": "f", "frau": "f", "fr": "f", "mrs": "f", "ms": "f", "miss": "f",
    "patientin": "f",
}
_BEFORE_NAME = re.compile(
    r"(Herrn?|Frau|Hr\.|Fr\.|Mr\.?|Mrs\.?|Ms\.?|Miss|Patientin|Patient)?\s*:?\s*((?:Dr\.(?:\s?med\.)?|Prof\.|PD)\s*)*$"
)
_ACADEMIC = re.compile(r"(?:Dr\.|Prof\.|PD)\s*(?:med\.\s*)?$")
_BIRTH_MARK = re.compile(
    r"(?:geb\.?|geboren(?:\s+am)?|born(?:\s+on)?|DOB|Geburtsdatum|Date\s+of\s+birth|\*)\s*:?\s*$", re.IGNORECASE
)
_ONLY_SEPARATORS = re.compile(r"^[\s,;(]*$")
_NEAR = 80


class Column(NamedTuple):
    """What a table column holds."""

    category: str | None = None  # ID, DOB, PERSON, ... (see tables.py)
    role: str | None = None  # for people: first, last, full, other; or gender
    key: str = ""
    visit_id: bool = False


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

    def classify(self, header: str | None, label: str | None = None) -> str | None:
        return None

    def column(self, header: str | None, label: str | None = None) -> Column:
        return Column(
            self.classify(header, label),
            column_role(header, label),
            column_key(header, label),
            is_visit_id(header, label),
        )

    def cell(self, category: str | None, value):
        return self.text(value) if isinstance(value, str) else value

    def row(self, columns: list[Column], values: list) -> list:
        """One table row. Handled as a whole, because the cells of a row belong to one person."""
        return [self.cell(_column_at(columns, i).category, v) for i, v in enumerate(values)]


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
    def __init__(self, pseudonymizer: Pseudonymizer, detectors: list[Detector]):
        super().__init__()
        self.pseudo = pseudonymizer
        self.base_detectors = list(detectors)
        self.detectors = list(detectors)
        self.registry = Registry(pseudonymizer)
        self.collecting = True  # first pass: only gather evidence about who is who
        self.current_file = ""

    def finish_collecting(self) -> None:
        """After the first pass: decide who is who, then also replace every value seen anywhere."""
        self.registry.resolve()
        self.collecting = False
        self.detectors = self.base_detectors + [KnownValueDetector(self.pseudo)]

    @property
    def detector_names(self) -> list[str]:
        return [d.name for d in self.detectors]

    def header(self, value: str) -> str:
        # Headers and labels are short and context-free: the AI guesses badly there
        # ("Geschlecht" as a person), so only rules and known values apply.
        return self.text(value, use_ai=False)

    def text(self, value: str, use_ai: bool = True) -> str:
        if not value or not any(c.isalnum() for c in value):
            return value
        spans = []
        for detector in self.detectors:
            if detector.name in _AI_SOURCES and not use_ai:
                continue
            spans.extend(detector.detect(value))
        spans = [s for s in spans if not TOKEN_RE.fullmatch(s.text) and not _ai_false_alarm(s)]
        chosen = resolve_overlaps(spans)
        if self.collecting:
            self._collect_from_text(value, chosen)
        out, last = [], 0
        for span in chosen:
            token = self._token_for_span(value, span, chosen)
            out.append(value[last : span.start])
            out.append(token)
            last = span.end
            self.stats[span.entity_type] += 1
            self.tokens.add(token)
        out.append(value[last:])
        return "".join(out)

    # -- free text ---------------------------------------------------------------
    def _token_for_span(self, value: str, span: Span, spans: list[Span]) -> str:
        if span.entity_type != "PERSON":
            return self.pseudo.token_for(span.entity_type, span.text)
        if self.collecting:
            return span.text  # who this is gets decided once all files were read
        gender, academic = _title_before(value, span)
        birth = _birth_date_next_to(value, span, spans)
        person, note = self.registry.person_for_mention(span.text, self.current_file, gender, academic, birth)
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
                self.registry.observe_mention(self.current_file, span.text, gender, academic, birth)

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
            elif column.category == "DOB":
                birth = parse_birth_date(value)
            elif column.category == "ID" and not column.visit_id:
                ids.add((column.key, text))
            elif column.role == "gender":
                gender = _GENDER_WORDS.get(text.casefold())
        canonical = full or " ".join(p for p in (first, last) if p)
        if not canonical:
            return None
        return Record(name_key(canonical), " ".join(canonical.split()), first, last, birth, frozenset(ids), gender)

    def row(self, columns: list[Column], values: list) -> list:
        record = self._record_of_row(columns, values)
        person: Person | None = None
        if record is not None:
            if self.collecting:
                self.registry.observe_record(record, self.current_file)
            else:
                person = self.registry.person_for_record(record)
        out = []
        for i, value in enumerate(values):
            column = _column_at(columns, i)
            if column.category == "PERSON" and column.role in _NAME_ROLES and not _blank(value):
                out.append(self._person_cell(column, value, person))
            else:
                out.append(self.cell(column.category, value))
        return out

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


def _birth_date_next_to(value: str, span: Span, spans: list[Span]):
    """"Max Müller, geb. 12.05.1975": the birth date that belongs to this mention of a name."""
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
    return is_stopword(span.text) or not any(c.isupper() for c in span.text)


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
