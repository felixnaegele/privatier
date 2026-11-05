"""The two directions of Privatier: anonymise (real -> token) and restore (token -> real).

File handlers don't care which direction they run in. They hand text, table
headers and table cells to a Transformer and write back whatever it returns.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter

from .detect.base import Detector, resolve_overlaps
from .detect.stopwords import is_stopword
from .pseudonyms import TOKEN_RE, KnownValueDetector, Pseudonymizer
from .tables import CATEGORY_TO_TYPE, classify_header, looks_like_date_column


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

    def cell(self, category: str | None, value):
        return self.text(value) if isinstance(value, str) else value


class Anonymizer(Transformer):
    def __init__(self, pseudonymizer: Pseudonymizer, detectors: list[Detector]):
        super().__init__()
        self.pseudo = pseudonymizer
        self.base_detectors = list(detectors)
        self.detectors = list(detectors)

    def enable_known_values(self) -> None:
        """After the first pass: also replace every value already seen anywhere."""
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
        out, last = [], 0
        for span in resolve_overlaps(spans):
            token = self.pseudo.token_for(span.entity_type, span.text)
            out.append(value[last : span.start])
            out.append(token)
            last = span.end
            self.stats[span.entity_type] += 1
            self.tokens.add(token)
        out.append(value[last:])
        return "".join(out)

    def classify(self, header: str | None, label: str | None = None) -> str | None:
        category = classify_header(header, label)
        if category is None and looks_like_date_column(header, label):
            self.warnings.append(
                f"Column '{header}' looks like it holds dates. Dates other than the birth date are kept "
                "as they are; check whether they could identify someone."
            )
        return category

    def cell(self, category: str | None, value):
        if value is None or (isinstance(value, float) and value != value):  # None / NaN
            return value
        if isinstance(value, str) and not value.strip():
            return value
        if category == "DOB":
            self.stats["DATE_OF_BIRTH_TO_YEAR"] += 1
            return _year_of(value, self)
        if category in CATEGORY_TO_TYPE:
            etype = CATEGORY_TO_TYPE[category]
            text = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
            if TOKEN_RE.fullmatch(text.strip()):
                return text
            token = self.pseudo.token_for(etype, text.strip())
            self.stats[etype] += 1
            self.tokens.add(token)
            return token
        return super().cell(category, value)


_AI_SOURCES = {"ner", "llm"}


def _ai_false_alarm(span) -> bool:
    """AI findings that are common research words or have no capital letter are ignored."""
    if span.source not in _AI_SOURCES:
        return False
    return is_stopword(span.text) or not any(c.isupper() for c in span.text)


def _year_of(value, anon: Anonymizer):
    """Birth dates are reduced to the year: still useful for age, far less identifying."""
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

    def text(self, value: str) -> str:
        def repl(m: re.Match[str]) -> str:
            token = f"{m.group(1).upper()}_{m.group(2)}"
            original = self.pseudo.original(token)
            if original is None:
                self.unknown[token] += 1
                return m.group(0)
            self.stats[m.group(1).upper()] += 1
            self.tokens.add(token)
            return original

        return TOKEN_RE.sub(repl, value) if value else value
