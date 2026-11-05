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

# All Latin letters, not only German ones: patients are also called Şahin, Çelik or Łukasiewicz.
_LATIN = [chr(c) for c in range(0xC0, 0x250)]
_UP = "A-Z" + "".join(c for c in _LATIN if c.isupper())
_LOW = "a-z" + "".join(c for c in _LATIN if c.islower())
NAME_WORD = rf"(?:[{_UP}]'(?=[{_UP}]))?[{_UP}][{_LOW}]+(?:[{_UP}][{_LOW}]+)?(?:-[{_UP}][{_LOW}]+)?"
_PARTICLES = r"(?:von|van|de|del|der|den|zu|zur|ten|ter|dos|da)"
NAME_SEQ = rf"(?:(?<!\w){_PARTICLES}\s+(?:{_PARTICLES}\s+)?)?{NAME_WORD}(?:\s+(?:{_PARTICLES}\s+(?:{_PARTICLES}\s+)?)?{NAME_WORD}){{0,2}}"

_MONTHS = (
    "januar|january|jan|februar|february|feb|märz|maerz|march|mär|mar|april|apr|"
    "mai|may|juni|june|jun|juli|july|jul|august|aug|september|sept|sep|"
    "oktober|october|okt|oct|november|nov|dezember|december|dez|dec"
)

# Words that commonly follow a title but are not names ("Patient Data").
_NOT_NAMES = {
    "Name", "Namen", "Data", "Daten", "Nummer", "Number", "Record", "Akte",
    "Information", "Informationen", "Status", "Alter", "Age", "Gruppe", "Group",
    # "Frau Schmidts Morbus Crohn", "Herr Müllers Ehefrau": where a name ends
    "Morbus", "Syndrom", "Diagnose", "Diagnosen", "Befund", "Therapie", "Station", "Zimmer", "Klinik",
    "Pat", "Patient", "Patientin", "Patienten", "Proband", "Probandin", "Kollege", "Kollegin", "Doktor",
    "Ehefrau", "Ehemann", "Ehegatte", "Ehegattin", "Tochter", "Sohn", "Mutter", "Vater", "Bruder", "Schwester",
    "Enkel", "Enkelin", "Familie", "Betreuer", "Betreuerin", "Partner", "Partnerin", "Angehörige", "Angehöriger",
    "Rücksprache", "Rückruf", "Termin", "Kontrolle", "Nach", "Am", "Seit", "Bei", "Wegen",
    "Lebensgefährte", "Lebensgefährtin", "Mann", "Onkel", "Tante", "Neffe", "Nichte", "Dolmetscher", "Dolmetscherin",
    "Frau", "Herr", "Herrn", "Sie", "Er", "Die", "Der", "Das", "Ich", "Wir", "Betr", "Betreff",
}
_RELATIVES = (
    r"Sohn|Tochter|Ehefrau|Ehemann|Ehegatte|Ehegattin|Mann|Partner(?:in)?|Lebensgefährt(?:e|in)|Mutter|Vater|Bruder|"
    r"Schwester|Enkel(?:in)?|Onkel|Tante|Neffe|Nichte|Betreuer(?:in)?|Dolmetscher(?:in)?|Familie"
)
_COLLEAGUES = r"Kollegin|Kollege|Oberarzt|Oberärztin|Chefarzt|Chefärztin|Assistenzarzt|Assistenzärztin|Hausarzt|Hausärztin"
_FIRM = r"GmbH|mbH|AG|KG|OHG|UG|e\.\s?V\.|Gbr|GbR"
_INSTITUTION = r"Klinikum|Universitätsklinikum|Uniklinikum|Krankenhaus|Klinik\s+am|Klinik|Praxis|Pflegeheim|Seniorenheim|Hospital"
_INITIALS = rf"(?:[{_UP}]\.\s*)*"


_WRAPPED_LINE = 60  # characters; shorter lines ended on purpose


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
    Rule("case_number", "ID", _r(r"\b[A-Z]{1,4}-\d{4}-\d{3,}\b")),  # F-2024-00871
    Rule("svnr_de", "ID", _r(r"\b\d{2}\s?\d{6}\s?[A-Z]\s?\d{3}\b")),  # German social security no.
    Rule("ssn_us", "ID", _r(r"\b\d{3}-\d{2}-\d{4}\b")),
    Rule(
        "id_labelled",
        "ID",
        _r(
            r"(?:Fallnummer|Fall-?Nr\.?|Patienten-?(?:ID|Nr\.?|nummer)|Pat\.?-?(?:ID|Nr\.?)|MRN|"
            r"Patient\s+ID|Case\s+(?:No\.?|ID|number)|Aktenzeichen|Az\.|Versichertennummer|"
            r"Versicherten-?Nr\.?|Record\s+(?:No\.?|number)|Probanden-?(?:ID|Nr\.?)|"
            r"Personalausweis(?:-?Nr\.?|nummer)?|Ausweis(?:-?Nr\.?|nummer)?|Reisepass(?:-?Nr\.?|nummer)?)"
            r"\s*[:#.]?\s*((?=[A-Za-z0-9/-]*\d)[A-Za-z0-9][A-Za-z0-9/-]{2,})"
        ),
        group=1,
    ),
    # --- dates --------------------------------------------------------------
    Rule("date_numeric", "DATE", _r(r"(?<![\d.])(\d{1,2})[./-](\d{1,2})[./-](?:\d{4}|\d{2})(?![\d.]\d)")),
    # 12031948 or 19480312, e.g. in a folder name. A boundary may be "_".
    Rule(
        "date_compact",
        "DATE",
        _r(r"(?<![^\W_])(?:(?:0[1-9]|[12]\d|3[01])(?:0[1-9]|1[0-2])(?:19|20)\d{2}|(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(?![^\W_])"),
    ),
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
    Rule(
        "street_without_number",
        "ADDRESS",
        _r(rf"(?<![\w-])[{_UP}][{_LOW}-]*(?:straße|strasse)\b|\b[{_UP}][{_LOW}]+[\s-](?:Straße|Strasse)\b"),
    ),
    Rule("postcode_labelled", "LOCATION", _r(rf"(?:PLZ|D-)\s*:?\s*(\d{{5}}(?:\s+{NAME_WORD})?)"), group=1),
    # --- names with a clear hint -------------------------------------------
    Rule(
        "name_after_title",
        "PERSON",
        _r(
            r"(?:Herrn?|Frau|Hr\.|Fr\.|Mr\.?|Mrs\.?|Ms\.?|Miss|Patientin|Patient|Pat\.)"
            r"(?:\s+(?:Dr\.(?:\s?med\.)?|Prof\.|PD|Dipl\.-?\s?[\w-]+\.?|M\.\s?Sc\.|B\.\s?Sc\.))*\s+"
            rf"{_INITIALS}({NAME_SEQ})"
        ),
        group=1,
    ),
    Rule(
        "name_after_academic_title",
        "PERSON",
        _r(rf"(?:Dr\.(?:\s?med\.)?|Prof\.|Dipl\.-?\s?[\w-]+\.?|M\.\s?Sc\.|B\.\s?Sc\.)\s+{_INITIALS}({NAME_SEQ})"),
        group=1,
    ),
    Rule("name_after_relative", "PERSON", _r(rf"\b(?:{_RELATIVES})[,:]?\s+({NAME_SEQ})"), group=1),
    # Whatever stands right before a birth date is a person: "Yıldırım, Emine, geb. 11.04.1966"
    Rule(
        "name_before_birth_date",
        "PERSON",
        _r(rf"({NAME_WORD},\s+{NAME_WORD}|{NAME_SEQ})(?=,?\s*\(?\s*(?:\*|geb\.|geboren|born\b))"),
        group=1,
    ),
    # --- places and organisations with a clear shape -------------------------
    Rule(
        "postcode_and_city",
        "LOCATION",
        _r(rf"(?:^|(?<=[\s,(]))(\d{{5}}\s+{NAME_WORD})(?=\s*(?:[,.;)\n]|$))", re.MULTILINE),
        group=1,
    ),
    Rule("company", "ORG", _r(rf"((?:{NAME_WORD}\s+){{1,3}}(?:{_FIRM}))(?!\w)")),
    Rule("institution", "ORG", _r(rf"((?:{_INSTITUTION})\s+{NAME_WORD}(?:\s+{NAME_WORD})?)"), group=1),
    Rule("name_after_colleague", "PERSON", _r(rf"\b(?:{_COLLEAGUES})\s+({NAME_SEQ})"), group=1),
    Rule("name_in_greeting", "PERSON", _r(rf"\b(?:Liebe[rs]?|Hallo)\s+({NAME_SEQ})"), group=1),
    Rule("name_before_email", "PERSON", _r(rf"({NAME_SEQ})\s*<[\w.+-]+@"), group=1),
    Rule(
        "name_labelled",
        "PERSON",
        _r(
            r"(?:[Nn]ame|Patientenname|Patient name|Vorname|Nachname|Surname|First name|Last name|"
            r"Patient|Patientin|Proband|Probandin|Angehörige[rn]?)[\"']?\s*:\s*[\"']?"
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
                if rule.name == "date_numeric" and not (1 <= int(m.group(1)) <= 31 and 1 <= int(m.group(2)) <= 12):
                    continue  # a dose like 10-0-10 is not a date
                if rule.entity_type == "PERSON":
                    value = _cut_at_line_end(text, start, value)
                    value, start = _trim_non_names(value, start)
                    if not value:
                        continue
                spans.append(Span(start, start + len(value), rule.entity_type, value, "pattern"))
        return spans


def _cut_at_line_end(text: str, start: int, value: str) -> str:
    """"Herr Max Müller" + new line + "Geburtsdatum: ..." : the next line is not part of the name.

    Only a long line that was wrapped automatically can continue a name on the next line.
    """
    match = re.search(r"\s*\n\s*", value)
    if match is None:
        return value
    line_start = text.rfind("\n", 0, start) + 1
    wrapped = start + match.start() - line_start >= _WRAPPED_LINE
    after = value[match.end() :]
    next_word_end = start + match.end() + len(after.split()[0]) if after.split() else start + len(value)
    if wrapped and text[next_word_end : next_word_end + 1] != ":":
        return value
    return value[: match.start()]


def _trim_non_names(value: str, start: int) -> tuple[str, int]:
    """A name stops at the first word that cannot be part of it; leading such words are dropped."""
    words = list(re.finditer(r"\S+", value))
    begin = 0
    while begin < len(words) and words[begin].group().strip(",.") in _NOT_NAMES:
        begin += 1
    end = begin
    while end < len(words) and words[end].group().strip(",.") not in _NOT_NAMES:
        end += 1
    if begin == end:
        return "", start
    first, last = words[begin], words[end - 1]
    trimmed = value[first.start() : last.end()].rstrip(",")
    if trimmed.islower():
        return "", start  # only particles like "van" are left
    return trimmed, start + first.start()
