"""Deciding who is who: one person gets one code, and two people never share one.

A name alone does not identify anyone: two patients can both be called Max
Müller, and sometimes only the date of birth tells them apart. So all evidence
from the whole project is collected first (table rows, and names followed by a
birth date in free text), and only then are people told apart:

  * Same name + same birth date or same ID            -> the same person
  * Same name + different birth date                  -> different people
  * Same name + different patient ID in the same kind
    of column                                         -> different people
  * Same name, no evidence either way                 -> kept apart, and Privatier asks

The rule behind all of this: Privatier never assumes. What the data does not
settle stays apart and becomes a question, using codes only, so that real names
never reach the audit log or the screen. One switch answers the most common
question for a whole project: link_by_name says that an identical name without
any evidence is the same person.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import NamedTuple

from .pseudonyms import Pseudonymizer

_TITLES = {"dr", "med", "prof", "pd", "herr", "herrn", "frau", "hr", "fr", "mr", "mrs", "ms", "miss"}
_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

_DATE_DOTS = re.compile(r"^(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4}|\d{2})$")
_DATE_SLASH = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})$")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_YEAR_ONLY = re.compile(r"^(19|20)\d{2}$")
_MONTH_NUMBERS = {
    "januar": 1, "jan": 1, "january": 1, "februar": 2, "feb": 2, "february": 2, "märz": 3, "maerz": 3, "mär": 3,
    "mar": 3, "march": 3, "april": 4, "apr": 4, "mai": 5, "may": 5, "juni": 6, "jun": 6, "june": 6, "juli": 7,
    "jul": 7, "july": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "oktober": 10, "okt": 10,
    "oct": 10, "october": 10, "november": 11, "nov": 11, "dezember": 12, "dez": 12, "dec": 12, "december": 12,
}
_DATE_WORDS_DMY = re.compile(r"^(\d{1,2})\.?\s+([^\W\d]+)\.?,?\s+(\d{4})$")
_DATE_WORDS_MDY = re.compile(r"^([^\W\d]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$")


# --------------------------------------------------------------------------- names
def _fold(text: str) -> str:
    """Müller, MUELLER and Mueller compare equal; so do Weiß and Weiss."""
    decomposed = unicodedata.normalize("NFKD", text.casefold().translate(_FOLD))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def name_parts(text: str) -> tuple[str, ...]:
    """The words of a name in comparable form, without titles."""
    words = re.split(r"[\s,]+", _fold(text))
    return tuple(w for w in (word.strip(".") for word in words) if w and w not in _TITLES)


def name_key(text: str) -> tuple[str, ...]:
    """"Müller, Max" and "Max Mueller" give the same key, as do "Hans-Jürgen" and "Hans Jürgen"."""
    return tuple(sorted(word for part in name_parts(text) for word in part.split("-") if word))


def surname_first(text: str) -> tuple[str, str] | None:
    """"Müller, Max" -> ("Max", "Müller")."""
    if text.count(",") != 1:
        return None
    last, first = (part.strip() for part in text.split(","))
    return (first, last) if first and last else None


# --------------------------------------------------------------------------- birth dates
@dataclass(frozen=True)
class BirthDate:
    """A birth date as far as it is known.

    `dates` usually holds one ISO date. It holds two when the format is ambiguous
    (03/04/1975 can be 3 April or 4 March), and none when only the year is known.
    """

    dates: frozenset[str]
    year: int | None
    raw: str

    def same_person_possible(self, other: BirthDate) -> bool:
        if self.dates and other.dates:
            return bool(self.dates & other.dates)
        years_self = self._years()
        years_other = other._years()
        return bool(years_self & years_other) if years_self and years_other else True

    def _years(self) -> set[int]:
        return {int(d[:4]) for d in self.dates} | ({self.year} if self.year else set())

    @property
    def key(self) -> tuple[str, ...]:
        return tuple(sorted(self.dates)) or (str(self.year),)

    def to_dict(self) -> dict:
        return {"dates": sorted(self.dates), "year": self.year, "raw": self.raw}

    @classmethod
    def from_dict(cls, data: dict) -> BirthDate:
        return cls(frozenset(data["dates"]), data["year"], data["raw"])


def _iso(year: int, month: int, day: int) -> str | None:
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def _centuries(year_text: str) -> list[int]:
    if len(year_text) == 4:
        return [int(year_text)]
    return [1900 + int(year_text), 2000 + int(year_text)]  # "12.05.30" does not say which century


def parse_birth_date(value) -> BirthDate | None:
    if value is None or (isinstance(value, float) and value != value):
        return None
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):  # date, datetime, Timestamp
        if value != value:  # NaT
            return None
        iso = f"{int(value.year):04d}-{int(value.month):02d}-{int(value.day):02d}"
        return BirthDate(frozenset({iso}), int(value.year), iso)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    raw = " ".join(str(value).split())
    if not raw:
        return None
    if _YEAR_ONLY.match(raw):
        return BirthDate(frozenset(), int(raw), raw)
    candidates: set[str | None] = set()
    if m := _DATE_ISO.match(raw):
        candidates.add(_iso(int(m[1]), int(m[2]), int(m[3])))
    elif m := _DATE_DOTS.match(raw):
        for year in _centuries(m[3]):
            candidates.add(_iso(year, int(m[2]), int(m[1])))
    elif m := _DATE_SLASH.match(raw):
        for year in _centuries(m[3]):
            candidates.add(_iso(year, int(m[2]), int(m[1])))  # day first
            candidates.add(_iso(year, int(m[1]), int(m[2])))  # month first
    elif m := _DATE_WORDS_DMY.match(raw):
        if month := _MONTH_NUMBERS.get(m[2].casefold()):
            candidates.add(_iso(int(m[3]), month, int(m[1])))
    elif m := _DATE_WORDS_MDY.match(raw):
        if month := _MONTH_NUMBERS.get(m[1].casefold()):
            candidates.add(_iso(int(m[3]), month, int(m[2])))
    dates = frozenset(c for c in candidates if c)
    if not dates:
        return None
    years = {int(d[:4]) for d in dates}
    return BirthDate(dates, years.pop() if len(years) == 1 else None, raw)


# --------------------------------------------------------------------------- evidence
@dataclass
class Record:
    """Everything one table row (or one sentence) says about one person."""

    key: tuple[str, ...]
    canonical: str
    first: str | None = None
    last: str | None = None
    birth: BirthDate | None = None
    ids: frozenset[tuple[str, str]] = frozenset()  # (column, value): patient-level IDs only
    gender: str | None = None
    files: set[str] = field(default_factory=set)
    spellings: set[str] = field(default_factory=set)
    row: tuple | None = None  # without evidence, a row only speaks for itself

    @property
    def identity(self) -> tuple:
        place = self.row if not (self.birth or self.ids) else None
        return (self.key, self.birth.key if self.birth else None, tuple(sorted(self.ids)), place)


@dataclass
class Person:
    token: str
    key: tuple[str, ...]
    canonical: str
    births: list[BirthDate] = field(default_factory=list)
    ids: set[tuple[str, str]] = field(default_factory=set)
    gender: str | None = None
    first_parts: set[str] = field(default_factory=set)
    last_parts: set[str] = field(default_factory=set)
    files: set[str] = field(default_factory=set)
    has_evidence: bool = False

    def absorb(self, record: Record) -> None:
        if record.birth and all(record.birth.key != b.key for b in self.births):
            self.births.append(record.birth)
        self.ids |= record.ids
        self.gender = self.gender or record.gender
        self.files |= record.files
        self.has_evidence = self.has_evidence or bool(record.birth or record.ids)
        if record.first:
            self.first_parts.update(name_parts(record.first))
        if record.last:
            self.last_parts.update(name_parts(record.last))

    def conflicts_with(self, record: Record) -> bool:
        if record.birth and self.births and not any(record.birth.same_person_possible(b) for b in self.births):
            return True
        mine: dict[str, set[str]] = {}
        for column, value in self.ids:
            mine.setdefault(column, set()).add(value)
        return any(column in mine and value not in mine[column] for column, value in record.ids)

    def shares_evidence_with(self, record: Record) -> bool:
        if record.birth and any(record.birth.dates & b.dates for b in self.births):
            return True
        # "Jg. 1961" and 23.08.1961: only the year is known, and it fits.
        if record.birth and any(
            (not record.birth.dates or not b.dates) and record.birth.same_person_possible(b) for b in self.births
        ):
            return True
        return bool({v for _, v in record.ids} & {v for _, v in self.ids})

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "key": list(self.key),
            "canonical": self.canonical,
            "births": [b.to_dict() for b in self.births],
            "ids": sorted(list(i) for i in self.ids),
            "gender": self.gender,
            "first_parts": sorted(self.first_parts),
            "last_parts": sorted(self.last_parts),
            "has_evidence": self.has_evidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Person:
        return cls(
            token=data["token"],
            key=tuple(data["key"]),
            canonical=data["canonical"],
            births=[BirthDate.from_dict(b) for b in data["births"]],
            ids={tuple(i) for i in data["ids"]},
            gender=data.get("gender"),
            first_parts=set(data.get("first_parts", [])),
            last_parts=set(data.get("last_parts", [])),
            has_evidence=data.get("has_evidence", False),
        )


def _fits(a: BirthDate, b: BirthDate) -> bool:
    """The same date, or only a year is known and it fits ("Jg. 1961" and 23.08.1961)."""
    return bool(a.dates & b.dates) or ((not a.dates or not b.dates) and a.same_person_possible(b))


class Mention(NamedTuple):
    text: str
    gender: str | None
    academic: bool
    birth: BirthDate | None
    from_ai: bool
    relative: bool  # "seine Mutter Ingeborg Berger": someone other than the person the document is about


@dataclass
class FileEvidence:
    birth_dates: list[BirthDate] = field(default_factory=list)
    ids: set[str] = field(default_factory=set)
    mentions: list[Mention] = field(default_factory=list)
    people: set[str] = field(default_factory=set)  # tokens of people who appear in this file


# --------------------------------------------------------------------------- registry
class Registry:
    def __init__(self, pseudonymizer: Pseudonymizer, link_by_name: bool = False):
        self.pseudo = pseudonymizer
        self.link_by_name = link_by_name
        self.records: dict[tuple, Record] = {}
        self.files: dict[str, FileEvidence] = {}
        self.people: list[Person] = [Person.from_dict(p) for p in pseudonymizer.people]
        self._by_token = {p.token: p for p in self.people}
        self._by_key: dict[tuple[str, ...], list[Person]] = {}
        for person in self.people:
            self._by_key.setdefault(person.key, []).append(person)
        self._record_owner: dict[tuple, Person] = {}
        self.review: list[str] = []  # questions for the user, codes only
        self.settled: list[str] = []  # decided by the data, for the audit log only

    def file(self, name: str) -> FileEvidence:
        return self.files.setdefault(name, FileEvidence())

    # -- collecting ----------------------------------------------------------
    def observe_record(self, record: Record, file: str) -> None:
        if not record.key:
            return
        stored = self.records.setdefault(record.identity, record)
        stored.files.add(file)
        stored.gender = stored.gender or record.gender
        stored.first = stored.first or record.first
        stored.last = stored.last or record.last
        stored.spellings |= {s for s in (record.canonical, record.first, record.last) if s}

    def observe_mention(
        self,
        file: str,
        text: str,
        gender: str | None,
        academic: bool,
        birth: BirthDate | None,
        from_ai: bool = False,
        relative: bool = False,
    ) -> None:
        self.file(file).mentions.append(Mention(text, gender, academic, birth, from_ai, relative))
        if birth and len(name_parts(text)) >= 2:
            self.observe_record(Record(name_key(text), " ".join(text.split()), birth=birth, gender=gender), file)

    # -- deciding ------------------------------------------------------------
    def resolve_records(self) -> None:
        """Step 1, after all files were read: turn tables and birth dates into people."""
        self._place_new_records()

    def resolve_mentions(self) -> None:
        """Step 2, once full names were also searched for in free text: who appears where."""
        self._place_new_records()
        for name, evidence in self.files.items():
            for person in self.people:
                if name in person.files:
                    evidence.people.add(person.token)
        # Names that only ever appear in free text, without a birth date.
        for name, evidence in self.files.items():
            for mention in evidence.mentions:
                key = name_key(mention.text)
                if self._surname_of_someone_here(mention.text, name) is not None:
                    continue  # "Herr van den Berg" in a letter about Willem van den Berg
                if len(name_parts(mention.text)) >= 2 and not mention.academic and key not in self._by_key:
                    self._new_person(Record(key, " ".join(mention.text.split()), files={name}))
        for name, evidence in self.files.items():
            for mention in evidence.mentions:
                person = None
                if len(name_parts(mention.text)) >= 2:
                    person = self._match_full_name(mention.text, name, mention.academic, mention.birth)
                    if person is not None:
                        person.files.add(name)
                        if not mention.relative:
                            evidence.people.add(person.token)
                if person is None and not mention.from_ai:
                    # Found by a rule, so it is reliable: also look for it everywhere else.
                    # A single AI guess is not, one wrong word would spread through the whole project.
                    self.pseudo.token_for("PERSON", mention.text)
        self._register_spellings()
        for key, people in self._by_key.items():
            if len(people) > 1:
                # Birth dates or IDs settled this, so there is nothing to ask. It stays on record.
                codes = ", ".join(p.token for p in people)
                self.settled.append(f"{codes} have the same name but are different people, by birth date or ID.")
        owners: dict[tuple[str, str], list[str]] = {}
        for person in self.people:
            for column_value in sorted(person.ids):
                owners.setdefault(column_value, []).append(person.token)
        for shared in dict.fromkeys(tuple(tokens) for tokens in owners.values() if len(tokens) > 1):
            self.review.append(
                f"{', '.join(shared)} are different people with the same ID number in the original data. "
                "The ID keeps one code, as in the original: please check whether these IDs come from different lists."
            )
        self.pseudo.people = [p.to_dict() for p in self.people]

    def _place_new_records(self) -> None:
        new = [r for r in self.records.values() if r.identity not in self._record_owner]
        with_evidence = [r for r in new if r.birth or r.ids]
        without = [r for r in new if not (r.birth or r.ids)]
        # Most complete first, so that weaker records attach to well-identified people.
        with_evidence.sort(key=lambda r: (not (r.birth and r.birth.dates), not r.ids))
        for record in with_evidence + without:
            self._place(record)
        self._register_spellings()

    def _register_spellings(self) -> None:
        for record in self.records.values():
            owner = self._record_owner.get(record.identity)
            if owner is not None:
                for spelling in record.spellings:
                    self.pseudo.form_of(owner.token, spelling, self.form_for(owner, spelling))

    def _new_person(self, record: Record) -> Person:
        person = Person(self.pseudo.new_person(record.canonical), record.key, record.canonical)
        person.absorb(record)
        self.people.append(person)
        self._by_token[person.token] = person
        self._by_key.setdefault(record.key, []).append(person)
        return person

    def _place(self, record: Record) -> None:
        same_name = self._by_key.get(record.key, [])
        fitting = [p for p in same_name if not p.conflicts_with(record)]
        sharing = [p for p in fitting if p.shares_evidence_with(record)]
        chosen: Person | None = None
        if len(sharing) == 1:
            chosen = sharing[0]
        elif not sharing and len(fitting) == 1 and self.link_by_name:
            chosen = fitting[0]  # the user said an identical name is the same person
        if chosen is None:
            chosen = self._new_person(record)
            self._flag_same_birth_different_id(chosen, same_name, record)
            if len(fitting) > 1 or len(sharing) > 1:
                self.review.append(
                    f"{chosen.token}: not enough information to tell which of "
                    f"{', '.join(p.token for p in fitting)} this is, so it was kept apart."
                )
            elif len(fitting) == 1:
                self.review.append(
                    f"{chosen.token} may be {fitting[0].token}: same name, but no birth date or ID confirms it, "
                    "so they were kept apart."
                )
        else:
            read_two_ways = [b for b in (record.birth, *chosen.births) if b and len(b.dates) > 1]
            if read_two_ways:
                self.review.append(
                    f"{chosen.token}: a birth date could be read two ways (day/month), and one reading matched."
                )
            chosen.absorb(record)
        self._record_owner[record.identity] = chosen

    def _flag_same_birth_different_id(self, person: Person, same_name: list[Person], record: Record) -> None:
        if not record.birth:
            return
        for other in same_name:
            if other is person:
                continue
            if any(record.birth.dates & b.dates for b in other.births):
                self.review.append(
                    f"{person.token} and {other.token} have the same name and birth date but different "
                    "patient IDs. They were kept apart: please check whether this is one person."
                )

    # -- looking up ----------------------------------------------------------
    def person_for_record(self, record: Record) -> Person | None:
        return self._record_owner.get(record.identity)

    def person_of_token(self, token: str) -> Person | None:
        return self._by_token.get(token)

    def _evidence_match(self, people: list[Person], births: list[BirthDate], ids: set[str]) -> Person | None:
        found = [
            p
            for p in people
            if any(_fits(b, o) for b in births for o in p.births) or ids & {v for _, v in p.ids}
        ]
        return found[0] if len(found) == 1 else None

    def _match_full_name(self, text: str, file: str, academic: bool, birth: BirthDate | None) -> Person | None:
        people = self._by_key.get(name_key(text), [])
        if not people:
            return None
        if birth:  # a birth date right next to the name is the strongest evidence
            exact = self._evidence_match(people, [birth], set())
            if exact is not None:
                return exact
            return None
        evidence = self.file(file)
        exact = self._evidence_match(people, evidence.birth_dates, evidence.ids)
        if exact is not None:
            return exact
        if len(people) == 1 and not academic and (self.link_by_name or file in people[0].files):
            return people[0]  # the same full name in the document it was found in
        return None

    def person_for_mention(
        self,
        text: str,
        file: str,
        gender: str | None,
        academic: bool,
        birth: BirthDate | None,
        row_person: Person | None = None,
    ) -> tuple[Person | None, str | None]:
        """Who a name in free text refers to, plus a review note if that is not certain."""
        parts = name_parts(text)
        if not parts:
            return None, None
        if len(parts) >= 2:
            person = self._match_full_name(text, file, academic, birth)
            if person is None and (part_of := self._surname_of_someone_here(text, file)) is not None:
                if self.link_by_name:
                    return part_of, None
                return None, f"a surname here may belong to {part_of.token}: kept apart, please check."
            if person is None:
                count = len(self._by_key.get(name_key(text), []))
                if count > 1:
                    return None, f"a name here fits {count} different people, so it was kept apart from them."
                if count == 1:
                    return None, f"a name here may be {self._by_key[name_key(text)][0].token}: same name, but nothing "\
                                 "confirms it, so it was kept apart."
                return None, None
            return person, None
        if row_person is not None and self._part_fits(parts[0], row_person):
            if self.link_by_name:
                return row_person, None
            return None, f"a name in a note may refer to {row_person.token}: kept apart, please check."
        candidate = self._match_single_name(parts[0], file, gender)
        if candidate is not None and not self.link_by_name:
            return None, f"a surname here may belong to {candidate.token}: kept apart, please check."
        return candidate, None

    def _surname_of_someone_here(self, text: str, file: str) -> Person | None:
        """A surname of several words: all of them belong to exactly one longer name in this document."""
        words = set(name_key(text))
        if len(words) < 2:
            return None
        fitting = [
            self._by_token[token]
            for token in self.file(file).people
            if words < set(self._by_token[token].key)
        ]
        return fitting[0] if len(fitting) == 1 else None

    def _match_single_name(self, part: str, file: str, gender: str | None) -> Person | None:
        """"Herr Müller" can only be linked if one person in this very document fits."""
        fitting = []
        for token in self.file(file).people:
            person = self._by_token[token]
            if gender and person.gender and gender != person.gender:
                continue
            if self._part_fits(part, person):
                fitting.append(person)
        return fitting[0] if len(fitting) == 1 else None

    @staticmethod
    def _part_fits(part: str, person: Person) -> bool:
        words = part.split("-")
        genitive = part[:-1].split("-") if part.endswith(("s", "'")) else []
        return all(w in person.key for w in words) or bool(genitive and all(w in person.key for w in genitive))

    def form_for(self, person: Person, text: str) -> str:
        """F for a first name, L for a surname, V for any other spelling."""
        parts = name_parts(text)
        if len(parts) == 1:
            if parts[0] in person.first_parts:
                return "F"
            if parts[0] in person.last_parts:
                return "L"
            words = name_parts(person.canonical)
            if words and parts[0] == words[0]:
                return "F"
            if words and parts[0] == words[-1]:
                return "L"
        return "V"
