"""Rule-based detection (German + English).

These rules are predictable and auditable: the same input always gives the
same result, and every rule is readable below. They catch things with a
recognisable shape (emails, phone numbers, dates, IBANs, insurance numbers,
labelled IDs, street addresses) and names that follow a title or a label
("Frau Dr. Schmidt", "Name: Müller, Max", "Mr. Smith").

Free-standing names without such a hint are the job of the local AI layer
(see gliner_detector.py) and of known-value propagation (engine.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .base import Span

_UP = "A-ZÄÖÜ"
_LOW = "a-zäöüßàáâçèéêëíîïñóôúûý"
NAME_WORD = rf"(?:[{_UP}]'(?=[{_UP}]))?[{_UP}][{_LOW}]+(?:[{_UP}][{_LOW}]+)?(?:-[{_UP}][{_LOW}]+)?"
NAME_SEQ = rf"{NAME_WORD}(?:\s+{NAME_WORD}){{0,2}}"

_MONTHS = (
    "januar|january|jan|februar|february|feb|märz|maerz|march|mär|mar|april|apr|"
    "mai|may|juni|june|jun|juli|july|jul|august|aug|september|sept|sep|"
    "oktober|october|okt|oct|november|nov|dezember|december|dez|dec"
)

# Words that commonly follow a title but are not names ("Patient Data").
_NOT_NAMES = {
    "Name", "Namen", "Data", "Daten", "Nummer", "Number", "Record", "Akte",
    "Information", "Informationen", "Status", "Alter", "Age", "Gruppe", "Group",
}


@dataclass(frozen=True)
class Rule:
    name: str
    entity_type: str
    regex: re.Pattern[str]
    group: int = 0  # which regex group holds the sensitive part


def _r(pattern: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(pattern, flags)


RULES: list[Rule] = [
    # --- contact data -------------------------------------------------------
    Rule("email", "EMAIL", _r(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    Rule(
        "phone_international",
        "PHONE",
        _r(r"(?<![\w+])(?:\+|00)\d{1,3}[\s./-]?(?:\(0\)[\s./-]?)?\d{2,5}(?:[\s./-]?\d{2,}){1,4}(?!\w)"),
    ),
    Rule(
        "phone_national_de",
        "PHONE",
        _r(r"(?<![\w.,])(?:\(0\d{2,5}\)\s?|0\d{2,5}[\s/-])\d{3,}(?:[\s-]?\d{2,})*(?!\w)"),
    ),
    Rule("phone_us", "PHONE", _r(r"(?<!\w)\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\w)")),
    Rule(
        "phone_labelled",
        "PHONE",
        _r(r"(?:Tel\.?|Telefon|Phone|Mobil|Mobile|Handy|Fax)\s*[:.]?\s*([+\d(][\d\s()/.-]{5,}\d)"),
        group=1,
    ),
    # --- banking / insurance / national IDs --------------------------------
    Rule("iban", "IBAN", _r(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b")),
    Rule("kvnr_de", "ID", _r(r"\b[A-Z]\d{9}\b")),  # German health insurance number
    Rule("svnr_de", "ID", _r(r"\b\d{2}\s?\d{6}\s?[A-Z]\s?\d{3}\b")),  # German social security no.
    Rule("ssn_us", "ID", _r(r"\b\d{3}-\d{2}-\d{4}\b")),
    Rule(
        "id_labelled",
        "ID",
        _r(
            r"(?:Fallnummer|Fall-?Nr\.?|Patienten-?(?:ID|Nr\.?|nummer)|Pat\.?-?(?:ID|Nr\.?)|MRN|"
            r"Patient\s+ID|Case\s+(?:No\.?|ID|number)|Aktenzeichen|Az\.|Versichertennummer|"
            r"Versicherten-?Nr\.?|Record\s+(?:No\.?|number)|Probanden-?(?:ID|Nr\.?))"
            r"\s*[:#.]?\s*((?=[A-Za-z0-9/-]*\d)[A-Za-z0-9][A-Za-z0-9/-]{2,})"
        ),
        group=1,
    ),
    # --- dates --------------------------------------------------------------
    Rule("date_numeric", "DATE", _r(r"(?<![\d.])\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2})(?![\d.]\d)")),
    Rule("date_iso", "DATE", _r(r"\b\d{4}-\d{2}-\d{2}\b")),
    Rule(
        "date_words_dmy",
        "DATE",
        _r(rf"\b(?:\d{{1,2}}\.?\s+)?(?:{_MONTHS})\.?\s+\d{{4}}\b", re.IGNORECASE),
    ),
    Rule(
        "date_words_mdy",
        "DATE",
        _r(rf"\b(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", re.IGNORECASE),
    ),
    # --- addresses ----------------------------------------------------------
    Rule(
        "street_de",
        "ADDRESS",
        _r(
            rf"(?:[{_UP}][{_LOW}]+[\s-](?:Straße|Strasse|Str\.|Weg|Gasse|Platz|Allee|Ring|Damm)"
            rf"|[{_UP}][{_LOW}-]*(?:straße|strasse|str\.|weg|gasse|platz|allee|ring|damm))"
            rf"\s+\d{{1,4}}\s?[a-z]?\b(?:,?\s+(?:D-)?\d{{5}}\s+{NAME_WORD})?"
        ),
    ),
    Rule(
        "street_en",
        "ADDRESS",
        _r(
            r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s){1,3}(?:Street|St\.|Avenue|Ave\.?|Road|Rd\.|Lane|Ln\.|"
            r"Drive|Boulevard|Blvd\.?|Court|Ct\.|Way|Terrace|Place|Pl\.|Square|Circle|Highway|Parkway)\b"
        ),
    ),
    Rule("postcode_labelled", "LOCATION", _r(rf"(?:PLZ|D-)\s*:?\s*(\d{{5}}(?:\s+{NAME_WORD})?)"), group=1),
    # --- names with a clear hint -------------------------------------------
    Rule(
        "name_after_title",
        "PERSON",
        _r(
            r"(?:Herrn?|Frau|Hr\.|Fr\.|Mr\.?|Mrs\.?|Ms\.?|Miss|Patientin|Patient|Pat\.)"
            r"(?:\s+(?:Dr\.(?:\s?med\.)?|Prof\.|PD))*\s+"
            rf"({NAME_SEQ})"
        ),
        group=1,
    ),
    Rule("name_after_academic_title", "PERSON", _r(rf"(?:Dr\.(?:\s?med\.)?|Prof\.)\s+({NAME_SEQ})"), group=1),
    Rule(
        "name_labelled",
        "PERSON",
        _r(
            r"(?:Name|Patientenname|Patient name|Vorname|Nachname|Surname|First name|Last name|"
            r"Patient|Patientin|Proband|Probandin|Angehörige[rn]?)\s*:\s*"
            rf"({NAME_WORD}(?:,?\s+{NAME_WORD}){{0,2}})"
        ),
        group=1,
    ),
]


class PatternDetector:
    name = "pattern"

    def __init__(self, rules: list[Rule] | None = None):
        self.rules = rules if rules is not None else RULES

    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for rule in self.rules:
            for m in rule.regex.finditer(text):
                start, end = m.span(rule.group)
                value = text[start:end].strip()
                if not value:
                    continue
                if rule.entity_type == "PERSON":
                    value, end = _trim_non_names(value, start)
                    if not value:
                        continue
                spans.append(Span(start, start + len(value), rule.entity_type, value, "pattern"))
        return spans


def _trim_non_names(value: str, start: int) -> tuple[str, int]:
    """Drop trailing/leading words like 'Data' from a detected name."""
    words = value.split()
    while words and words[-1].strip(",") in _NOT_NAMES:
        words.pop()
    if not words or words[0].strip(",") in _NOT_NAMES:
        return "", start
    trimmed = value[: value.rfind(words[-1]) + len(words[-1])]
    return trimmed, start + len(trimmed)
