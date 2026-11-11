"""Consistent pseudonyms: the same real value always gets the same token.

"Max Müller" becomes PERSON_0001 in every file of the project, just like a
subject ID in a clinical trial. The table that links tokens back to real
values is stored only in the encrypted key file (vault.py).
"""

from __future__ import annotations

import re
import secrets
import unicodedata

from .detect.base import ENTITY_TYPES, Span

# A code can carry a form suffix, because the same person can appear in different forms:
# PERSON_0001 is the full name, PERSON_0001_F the first name, PERSON_0001_L the surname and
# PERSON_0001_V1 another spelling. This keeps one visible identifier per person, and restoring
# still gives back exactly what was written. Codes may touch "_" ("Arztbrief_PERSON_0001").
# TERM is a word the user added on the review screen. No detector finds it, so it is not an entity type.
TOKEN_TYPES = (*ENTITY_TYPES, "TERM")

TOKEN_RE = re.compile(
    rf"(?<![^\W_])({'|'.join(TOKEN_TYPES)})[ _-]?(\d{{4,}})(?:_([A-Z]\d*)(?![^\W_]))?(?![^\W_])",
    re.IGNORECASE,
)

# Types whose real values are searched for again in every other file.
_PROPAGATE = {"PERSON", "ORG", "LOCATION", "ADDRESS", "ID", "EMAIL", "PHONE", "IBAN"}
_UMLAUTS_OUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})
_NAME_PART_SKIP = {"dr", "med", "prof", "herr", "frau", "mr", "mrs", "ms", "von", "van", "der", "den", "de"}


def _normalise(entity_type: str, value: str) -> str:
    v = " ".join(value.split()).casefold()
    if entity_type == "PERSON":  # "Müller, Max" == "Max Müller"
        v = " ".join(sorted(v.replace(",", " ").split()))
    return v


# A date glued to a word ("ECV12.3.2015") gives a code glued to a word: ECVDATE_0005, DATE_0005Reflux.
GLUED_TOKEN_RE = re.compile(rf"({'|'.join(TOKEN_TYPES)})_(\d{{4}})(?!\d)")


class Pseudonymizer:
    def __init__(self, random_codes: bool = False) -> None:
        self.random_codes = random_codes  # no key is kept: the code must not show the order of first appearance
        self._key_to_token: dict[tuple[str, str], str] = {}
        self._token_to_original: dict[str, str] = {}
        self._token_type: dict[str, str] = {}
        self._counters: dict[str, int] = {t: 0 for t in TOKEN_TYPES}
        self._forms: dict[tuple[str, str], str] = {}  # (base token, exact text) -> token
        self.people: list[dict] = []  # who is who, see identity.py

    # -- assigning tokens ------------------------------------------------------
    def _new_token(self, entity_type: str, original: str) -> str:
        if self.random_codes:
            token = f"{entity_type}_{secrets.randbelow(90_000_000) + 10_000_000}"
            while token in self._token_to_original:
                token = f"{entity_type}_{secrets.randbelow(90_000_000) + 10_000_000}"
        else:
            self._counters[entity_type] += 1
            token = f"{entity_type}_{self._counters[entity_type]:04d}"
        self._token_to_original[token] = original
        self._token_type[token] = entity_type
        return token

    def base_for(self, entity_type: str, value: str) -> str:
        """The code of a value, whatever its spelling."""
        key = (entity_type, _normalise(entity_type, value))
        token = self._key_to_token.get(key)
        if token is None:
            token = self._new_token(entity_type, " ".join(str(value).split()))
            self._key_to_token[key] = token
        return token

    def token_for(self, entity_type: str, value: str) -> str:
        return self.form_of(self.base_for(entity_type, value), str(value))

    def new_person(self, canonical: str) -> str:
        """A code of its own: two people with the same name must never share one."""
        return self._new_token("PERSON", canonical)

    def form_of(self, base: str, text: str, form: str = "V") -> str:
        """The code for this exact spelling, so that restoring gives back what was written."""
        text = " ".join(str(text).split())
        if text == self._token_to_original[base]:
            return base
        token = self._forms.get((base, text))
        if token is None:
            taken = sum(1 for (b, _), t in self._forms.items() if b == base and t.startswith(f"{base}_{form}"))
            if form == "V":
                suffix = f"V{taken + 1}"
            else:
                suffix = form if taken == 0 else f"{form}{taken + 1}"
            token = f"{base}_{suffix}"
            self._forms[(base, text)] = token
            self._token_to_original[token] = text
            self._token_type[token] = self._token_type[base]
        return token

    def original(self, token: str) -> str | None:
        return self._token_to_original.get(token)

    def __len__(self) -> int:
        return len(self._token_to_original)

    # -- known values for propagation -------------------------------------------
    def known_values(self) -> list[tuple[str, str]]:
        """(entity_type, value) pairs to look for everywhere, incl. name parts."""
        return values_to_look_for((self._token_type[token], original) for token, original in self._token_to_original.items())

    # -- saving / loading --------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "entries": [
                {"token": t, "type": self._token_type[t], "original": o}
                for t, o in self._token_to_original.items()
            ],
            "people": self.people,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Pseudonymizer:
        p = cls()
        p.people = data.get("people", [])
        person_tokens = {person["token"] for person in p.people}
        for e in data["entries"]:
            token, etype, original = e["token"], e["type"], e["original"]
            p._token_to_original[token] = original
            p._token_type[token] = etype
            m = TOKEN_RE.fullmatch(token)
            p._counters[etype] = max(p._counters.get(etype, 0), int(m.group(2)))
            base = f"{m.group(1).upper()}_{m.group(2)}"
            if m.group(3):
                p._forms[(base, original)] = token
            elif token not in person_tokens:  # people are matched by evidence, never by name alone
                p._key_to_token[(etype, _normalise(etype, original))] = token
        return p


def values_to_look_for(pairs) -> list[tuple[str, str]]:
    """From (entity_type, value) pairs: what is searched for in every file, incl. name parts."""
    out: set[tuple[str, str]] = set()
    for etype, original in pairs:
        if etype not in _PROPAGATE or not _worth_propagating(original):
            continue
        out.add((etype, original))
        if etype == "LOCATION" and (m := re.fullmatch(r"\d{5}\s+(.+)", original)):
            out.add((etype, m.group(1)))  # "26121 Oldenburg" also means Oldenburg on its own
        if etype == "PERSON":
            for part in re.split(r"[\s,]+", original):
                if _worth_propagating(part) and part.casefold().strip(".") not in _NAME_PART_SKIP and part[0].isupper():
                    out.add(("PERSON", part))
    # The same order in every run. A word known as a name and as something else counts as the name,
    # so that it is linked to its person.
    return sorted(out, key=lambda p: (-len(p[1]), p[0] != "PERSON", p[0], p[1]))


def _worth_propagating(value: str) -> bool:
    v = value.strip()
    if v.isdigit():
        return len(v) >= 5  # short numbers like "12" would match everywhere
    # "St." is three characters but no name: it would hit every "St. Jude Medical".
    return sum(c.isalnum() for c in v) >= 3


def _spellings(entity_type: str, value: str) -> set[str]:
    """A name is often written without umlauts: Müller / Mueller, Weiß / Weiss, Ayşe / Ayse."""
    found = {value, value.upper(), value.title()}
    if entity_type == "PERSON":
        plain = value.translate(_UMLAUTS_OUT)
        plain = "".join(c for c in unicodedata.normalize("NFKD", plain) if not unicodedata.combining(c))
        with_umlauts = value
        for written, umlaut in (("ae", "ä"), ("oe", "ö"), ("ue", "ü"), ("Ae", "Ä"), ("Oe", "Ö"), ("Ue", "Ü")):
            with_umlauts = with_umlauts.replace(written, umlaut)
        found |= {plain, plain.title(), plain.upper(), with_umlauts, value.replace("ss", "ß"), value.replace("ß", "ss")}
    return found


_GENITIVE = re.compile(r"(?:'s|s'|s|')$")


class KnownValueDetector:
    """Finds every value already identified anywhere in the project.

    `terms` are words the user added on the review screen. They are matched like a known name (whole
    word, with and without umlauts, the genitive), and in any mix of capital and small letters.
    `values` replaces the values of the key, to look for a list of values only.
    """

    name = "known"

    def __init__(self, pseudonymizer: Pseudonymizer | None = None, terms: list[str] | None = None, values=None):
        if values is None:
            values = pseudonymizer.known_values() if pseudonymizer is not None else []
        self._type_of: dict[str, str] = {}
        self._term_of: dict[str, str] = {}
        alternatives: list[tuple[str, bool]] = []
        for etype, value in values:
            for variant in _spellings(etype, value):
                if variant not in self._type_of:
                    self._type_of[variant] = etype
                    alternatives.append((variant, False))
        for term in terms or []:
            for variant in _spellings("PERSON", term):
                folded = " ".join(variant.split()).casefold()
                if folded and folded not in self._term_of:
                    self._term_of[folded] = term
                    alternatives.append((variant, True))
        alternatives.sort(key=lambda a: len(a[0]), reverse=True)

        def pattern(variant: str, any_case: bool) -> str:
            escaped = re.escape(variant).replace(r"\ ", r"\s+")
            return f"(?i:{escaped})" if any_case else escaped

        self._regex = (
            re.compile(
                # Boundaries: a letter or digit may not touch the match, but "_" may ("Arztbrief_Schmidt").
                r"(?<![^\W_])((?:" + "|".join(pattern(*a) for a in alternatives) + r")(?:'s|s'|s|')?)(?![^\W_])"
            )
            if alternatives
            else None
        )

    def term_of(self, text: str) -> str | None:
        """The added word behind a match, as the user wrote it."""
        whole = " ".join(text.split()).casefold()
        return self._term_of.get(whole) or self._term_of.get(_GENITIVE.sub("", whole))

    def detect(self, text: str) -> list[Span]:
        if self._regex is None:
            return []
        spans = []
        for m in self._regex.finditer(text):
            matched = m.group(1)
            whole = " ".join(matched.split())
            # A value the data already established keeps its own type, also when the user added it again.
            etype = self._type_of.get(whole) or ("TERM" if whole.casefold() in self._term_of else None)
            if etype is None:  # the genitive: "Herr Müllers", "Frau Schulz'", "Mr Smith's"
                base = _GENITIVE.sub("", whole)
                etype = self._type_of.get(base) or ("TERM" if base.casefold() in self._term_of else None)
                if etype is None or etype not in ("PERSON", "TERM") or len(base) < 4:
                    continue  # "Mais" is not the genitive of the surname Mai
            spans.append(Span(m.start(1), m.end(1), etype, matched, "known"))
        return spans
