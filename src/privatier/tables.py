"""Recognising sensitive columns in spreadsheets and data files by their header.

A column called "Nachname" or "Date of birth" is sensitive as a whole, even
when a single value ("Klein", "1980") would not look like a name or a
birthday on its own. Headers are matched in German and English.
"""

from __future__ import annotations

import re

# Order matters: the first matching rule wins.
_HEADER_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("BIRTH_YEAR", re.compile(r"geburtsjahr|geb_?jahr|jahrgang|birth_?year|year_?of_?birth|(^|_)yob($|_)")),
    ("DOB", re.compile(r"geb(urts)?_?dat|geburtstag|(^|_)dob($|_)|date_?of_?birth|birth_?date|birthday|(^|_)geb($|_)")),
    (
        "ID",
        re.compile(
            r"(^|_)(patient(en)?_?|pat_?|subject_?|proband(en)?_?)?id($|_)|(^|_)pid($|_)|"
            r"versuchsperson|(^|_)vpn?($|_)|teilnehmer_?(id|nr|nummer)|(^|_)code($|_)|kennung|pseudonym|"
            r"pat(ienten)?_?(nr|nummer|number|no)($|_)|proband(en)?_?(nr|nummer)|"
            r"fall_?n(umme)?r|case_?(id|no|num|number)|(^|_)mrn($|_)|medical_?record|"
            r"versicherten_?n|kvnr|sozialversicherung|svnr|(^|_)ssn($|_)|insurance_?(no|num|number|id)|"
            r"aktenzeichen|krankenkassen_?nr"
        ),
    ),
    ("EMAIL", re.compile(r"e_?mail|(^|_)mail($|_)")),
    ("PHONE", re.compile(r"telefon|(^|_)tel($|_)|phone|handy|(^|_)mobil|(^|_)fax($|_)")),
    (
        "ADDRESS",
        re.compile(
            r"adresse|anschrift|stra(ss|ß)e|street|address|wohnort|geburtsort|birth_?place|"
            r"(^|_)ort($|_)|(^|_)city($|_)|stadt|(^|_)plz($|_)|postleitzahl|(^|_)zip|postal|hausnummer"
        ),
    ),
    (
        "PERSON",
        re.compile(
            r"(^|_)(vor|nach|familien|patienten|ruf|geburts|mädchen|maedchen)?name(n)?($|_)|"
            r"first_?name|last_?name|surname|given_?name|full_?name|maiden_?name|"
            r"^patient(in)?$|arzt|aerztin|ärztin|physician|doctor|angehoerige|angehörige|"
            r"kontaktperson|contact_?person|next_?of_?kin|unterschrift|signature"
        ),
    ),
]

# Columns that hold dates other than the birth date (e.g. admission date).
_DATE_HINT = re.compile(r"datum|date|(^|_)tag($|_)|aufnahme|entlassung|admission|discharge|visit|termin")


def _norm(header: str) -> str:
    h = str(header).strip().lower()
    h = h.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "_", h).strip("_")


def classify_header(*names: str | None) -> str | None:
    """Return a category for a column, given its name and (optionally) its label."""
    for name in names:
        if not name:
            continue
        n = _norm(name)
        for category, rule in _HEADER_RULES:
            if rule.search(n):
                return category
    return None


def looks_like_date_column(*names: str | None) -> bool:
    return any(name and _DATE_HINT.search(_norm(name)) for name in names)


# Person columns that are about someone other than the row's patient.
_OTHER_PERSON = re.compile(
    r"arzt|aerztin|physician|doctor|angehoerig|kontaktperson|contact_?person|next_?of_?kin|"
    r"unterschrift|signature|maiden|geburts_?name|maedchen"
)
_FIRST_NAME = re.compile(r"vorname|first_?name|given_?name|rufname")
_LAST_NAME = re.compile(r"nachname|last_?name|surname|familienname")
_GENDER = re.compile(r"^(geschlecht|geschl|sex|sexus|gender)$")
# These IDs belong to one stay or case: one patient can have several without being two people.
_VISIT_ID = re.compile(r"fall|case|aktenzeichen|visit|besuch|aufnahme|admission")


def column_role(*names: str | None) -> str | None:
    """What a column says about the person a row describes: first, last, full, other or gender."""
    normalised = [_norm(name) for name in names if name]
    if any(_GENDER.search(n) for n in normalised):
        return "gender"
    if any(_OTHER_PERSON.search(n) for n in normalised):
        return "other"
    for n in normalised:
        if _FIRST_NAME.search(n):
            return "first"
        if _LAST_NAME.search(n):
            return "last"
    return "full"


def is_visit_id(*names: str | None) -> bool:
    return any(name and _VISIT_ID.search(_norm(name)) for name in names)


def column_key(*names: str | None) -> str:
    return next((_norm(name) for name in names if name), "")


# Category -> entity type used for the token
CATEGORY_TO_TYPE = {
    "PERSON": "PERSON",
    "ID": "ID",
    "ADDRESS": "ADDRESS",
    "EMAIL": "EMAIL",
    "PHONE": "PHONE",
}
