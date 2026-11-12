"""What the user sees before an export, and what they decided about it.

A Finding is one value Privatier would replace. It holds the real value, so it goes to the user's own
screen and nowhere else: never into a file, the audit log or the privacy report. The same holds for its
id, which is worked out from the value.

A Review holds the user's choices: values to leave as they are, and words that were missed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .pseudonyms import TOKEN_RE, _normalise

MIN_TERM_LENGTH = 2


@dataclass
class Finding:
    id: str  # the same for the same type and value, in every scan
    type: str  # PERSON, ID, DATE, ... as in the codes; BIRTH_DATE for a birth date column; TERM for an added word
    value: str  # as written where it was first found
    count: int  # how often it is replaced, or would be if it were not kept
    files: list[str]
    source: str  # column, rule, ai, known, added
    can_keep: bool
    kept: bool = False  # the user said to leave it, and it is left
    already_replaced: int = 0  # for an added word: places where it is replaced anyway, as another finding
    becomes: str = ""  # what it turns into at level 1, in plain words: "a name code (PERSON_…)", "the year 1961"


_KIND_OF_CODE = {
    "PERSON": "a name code", "ID": "an ID code", "DATE": "a date code", "ADDRESS": "an address code",
    "LOCATION": "a place code", "ORG": "an organisation code", "EMAIL": "an e-mail code", "PHONE": "a phone code",
    "IBAN": "a bank account code", "TERM": "a code",
}


def code_in_words(entity_type: str) -> str:
    """The kind of code, never a number: which number it gets is only settled when the copy is written."""
    return f"{_KIND_OF_CODE.get(entity_type, 'a code')} ({entity_type}_…)"


@dataclass
class ColumnOutline:
    """One column of a table: what it is treated as, and which values in it are replaced."""

    index: int
    header: str  # as in the file; "(column 3)" when the file gives it no name
    kind: str  # PERSON, ID, ADDRESS, EMAIL, PHONE, BIRTH_DATE, BIRTH_YEAR, DATE, AGE, SEX, TEXT, PLAIN
    becomes: str  # at level 1, in plain words
    values: list[tuple[str, int]]  # (finding id, how often in this column)
    total_values: int  # cells of the column that are not empty
    decided: str | None  # what the user said it is: DOB, KEEP_DATES, PERSON, ID, KEEP
    ref: tuple  # (file, table, column), the key of Decisions.columns
    choices: list[str] = field(default_factory=list)  # decisions that make sense for this kind


@dataclass
class TableOutline:
    name: str  # the sheet, or "" for a file that is one table
    columns: list[ColumnOutline]
    problem: str | None = None  # why its columns cannot be told apart; what is found in it is under the file's groups


@dataclass
class FileOutline:
    file: str
    tables: list[TableOutline]
    groups: list[tuple[str, list[tuple[str, int]]]]  # outside table columns: (type, [(finding id, how often)])


@dataclass
class Review:
    keep: set[str] = field(default_factory=set)  # ids of findings to leave exactly as written
    extra: list[str] = field(default_factory=list)  # words or names that were missed


def finding_key(entity_type: str, value: str) -> tuple[str, str]:
    return (entity_type, _normalise(entity_type, value))


def id_of_key(key: tuple[str, str]) -> str:
    return hashlib.sha256(f"{key[0]}\x1f{key[1]}".encode("utf-8")).hexdigest()[:16]


def finding_id(entity_type: str, value: str) -> str:
    return id_of_key(finding_key(entity_type, value))


def clean_terms(extra) -> list[str]:
    """The added words worth looking for: no blanks, nothing shorter than two characters, each once."""
    terms: list[str] = []
    seen: set[str] = set()
    for term in extra or []:
        if not isinstance(term, str):
            continue
        term = " ".join(term.split())
        if len(term) < MIN_TERM_LENGTH or not any(c.isalnum() for c in term) or TOKEN_RE.fullmatch(term):
            continue
        folded = term.casefold()
        if folded not in seen:
            seen.add(folded)
            terms.append(term)
    return terms
