"""The four privacy levels, and what each does to a value.

Level 1 is what Privatier always did. The higher levels reduce what can single someone out, so the
rule "every cell comes out exactly as it went in" holds at level 1 only.

Nothing here decides that an output is anonymous: see verdict() and uniqueness.py.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from .identity import parse_birth_date

MIN_GROUP = 5  # someone counts as hidden when at least 4 others share their characteristics


@dataclass(frozen=True)
class Level:
    number: int
    name: str
    summary: str
    dates: str  # exact, month, year, remove
    ages: str  # exact, band
    births: str  # year, decade
    keeps_free_text: bool
    keeps_letters: bool
    keeps_key: bool
    blanks_rare: bool
    folder_suffix: str


LEVELS = {
    1: Level(
        1, "Pseudonymised", "Names and IDs become codes, reversible with the key. Dates and ages stay exact.",
        "exact", "exact", "year", True, True, True, False, "_pseudonymised",
    ),
    2: Level(
        2, "Less detail", "As level 1, but dates keep only month and year. Ages stay exact. Reversible with the key.",
        "month", "exact", "year", True, True, True, False, "_less_detail",
    ),
    3: Level(
        3, "Strongly reduced", "No key. Dates keep only the year, ages become 10-year bands, free text and letters are left out.",
        "year", "band", "decade", False, False, False, False, "_reduced",
    ),
    4: Level(
        4, "Anonymisation attempt", "As level 3, but dates are removed, and details of patients who still stand out are blanked.",
        "remove", "band", "decade", False, False, False, True, "_level4",
    ),
}

# Ways of writing "no value". A code here would look like a person who is not there.
NO_VALUE = {
    "NA", "N/A", "N.A.", "n.a.", "n/a", "na", "#N/A", "NaN", "nan", "None", "none", "NONE", "null", "NULL", "unknown",
    "Unknown", "unbekannt", "Unbekannt", "k.A.", "k. A.", "keine Angabe", "missing", "Missing", "not available", "ND",
    "-", "--", "---", "?", "??", "???", ".",
}


def is_blank(value) -> bool:
    if value is None or (isinstance(value, float) and value != value):
        return True
    if value != value:  # NaT
        return True
    return isinstance(value, str) and (not value.strip() or value.strip() in NO_VALUE)


UNREAD = object()  # the value cannot be reduced, because it could not be read as a date
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_YEAR_MONTH = re.compile(r"^\s*(\d{4})-(\d{1,2})\s*$")
_MONTH_YEAR = re.compile(r"^\s*(\d{1,2})[./-](\d{4})\s*$")
_LEADING_NUMBER = re.compile(r"^\s*(\d{1,3})(?:[.,]\d+)?(?!\d)")


def _date_of(value):
    """The date as far as it can be read. With a time behind it ("12.05.2015 14:30") the time does not matter."""
    found = parse_birth_date(value)
    if found is None and isinstance(value, str) and value.split():
        found = parse_birth_date(value.split()[0])
    return found


def year_of(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if 1800 <= value <= 2200 and float(value).is_integer() else None
    found = _date_of(value)
    if found is not None and found.year:
        return found.year
    if found is not None:
        return None  # "12.05.30" does not say which century
    m = _YEAR.search(str(value))
    return int(m.group(1)) if m else None


def _month_of(value) -> str | UNREAD.__class__:
    if isinstance(value, str):
        if m := _YEAR_MONTH.match(value):
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
        if m := _MONTH_YEAR.match(value):
            return f"{int(m.group(2)):04d}-{int(m.group(1)):02d}"
    found = _date_of(value)
    if found is not None and len(found.dates) == 1:
        return next(iter(found.dates))[:7]
    # 03/04/2015 can be March or April. Never assume: the year is all that is certain.
    year = year_of(value)
    return year if year else UNREAD


def age_band(value) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        age = int(value)
    else:
        m = _LEADING_NUMBER.match(str(value))
        if not m:
            return None
        age = int(m.group(1))
    if age < 0 or age > 130:
        return None
    if age >= 90:
        return "90+"
    start = age // 10 * 10
    return f"{start}-{start + 9}"


def birth_decade(value) -> str | None:
    """Without a reference date an age cannot be worked out, so a birth date becomes its decade."""
    year = year_of(value)
    if not year:
        return None
    start = year // 10 * 10
    return f"{start}-{start + 9}"


def reduce_value(action: str, value):
    """What a cell becomes. Blank cells stay as they are."""
    if is_blank(value):
        return value
    if action in ("remove", "empty"):
        return None
    if action == "band":
        return age_band(value)
    if action == "decade":
        return birth_decade(value)
    if action == "month":
        return _month_of(value)
    if action == "year":
        return year_of(value)
    raise ValueError(f"Unknown action: {action}")


def date_action(level: Level) -> str | None:
    return None if level.dates == "exact" else level.dates


CHANGE_WORDS = {
    "month": "day removed (month and year stay)",
    "year": "year only",
    "remove": "removed",
    "band": "10-year bands",
    "decade": "decade of birth only",
    "empty": "free text emptied",
}


def is_date_object(value) -> bool:
    return isinstance(value, (dt.date, dt.datetime)) or (hasattr(value, "year") and hasattr(value, "day"))
