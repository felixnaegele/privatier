"""Consistent pseudonyms: the same real value always gets the same token.

"Max Müller" becomes PERSON_0001 in every file of the project, just like a
subject ID in a clinical trial. The table that links tokens back to real
values is stored only in the encrypted key file (vault.py).
"""

from __future__ import annotations

import re
import unicodedata

from .detect.base import ENTITY_TYPES, Span

# A code can carry a form suffix, because the same person can appear in different forms:
# PERSON_0001 is the full name, PERSON_0001_F the first name, PERSON_0001_L the surname and
# PERSON_0001_V1 another spelling. This keeps one visible identifier per person, and restoring
# still gives back exactly what was written. Codes may touch "_" ("Arztbrief_PERSON_0001").
TOKEN_RE = re.compile(
    rf"(?<![^\W_])({'|'.join(ENTITY_TYPES)})[ _-]?(\d{{4,}})(?:_([A-Z]\d*)(?![^\W_]))?(?![^\W_])",
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


class Pseudonymizer:
    def __init__(self) -> None:
        self._key_to_token: dict[tuple[str, str], str] = {}
        self._token_to_original: dict[str, str] = {}
        self._token_type: dict[str, str] = {}
        self._counters: dict[str, int] = {t: 0 for t in ENTITY_TYPES}
        self._forms: dict[tuple[str, str], str] = {}  # (base token, exact text) -> token
        self.people: list[dict] = []  # who is who, see identity.py

    # -- assigning tokens ------------------------------------------------------
    def _new_token(self, entity_type: str, original: str) -> str:
        self._counters[entity_type] += 1
        token = f"{entity_type}_{self._counters[entity_type]:04d}"
        self._token_to_original[token] = original
        self._token_type[token] = entity_type
        return token

    def token_for(self, entity_type: str, value: str) -> str:
        key = (entity_type, _normalise(entity_type, value))
        token = self._key_to_token.get(key)
        if token is None:
            token = self._new_token(entity_type, " ".join(str(value).split()))
            self._key_to_token[key] = token
        return self.form_of(token, str(value))

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
        out: set[tuple[str, str]] = set()
        for token, original in self._token_to_original.items():
            etype = self._token_type[token]
            if etype not in _PROPAGATE or not _worth_propagating(original):
                continue
            out.add((etype, original))
            if etype == "LOCATION" and (m := re.fullmatch(r"\d{5}\s+(.+)", original)):
                out.add((etype, m.group(1)))  # "26121 Oldenburg" also means Oldenburg on its own
            if etype == "PERSON":
                for part in re.split(r"[\s,]+", original):
                    if len(part) >= 3 and part.casefold().strip(".") not in _NAME_PART_SKIP and part[0].isupper():
                        out.add(("PERSON", part))
        return sorted(out, key=lambda p: -len(p[1]))

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


def _worth_propagating(value: str) -> bool:
    v = value.strip()
    if v.isdigit():
        return len(v) >= 5  # short numbers like "12" would match everywhere
    return len(v) >= 3


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


class KnownValueDetector:
    """Finds every value already identified anywhere in the project."""

    name = "known"

    def __init__(self, pseudonymizer: Pseudonymizer):
        values = pseudonymizer.known_values()
        self._type_of: dict[str, str] = {}
        alternatives: list[str] = []
        for etype, value in values:
            for variant in _spellings(etype, value):
                if variant not in self._type_of:
                    self._type_of[variant] = etype
                    alternatives.append(variant)
        alternatives.sort(key=len, reverse=True)
        self._regex = (
            re.compile(
                # Boundaries: a letter or digit may not touch the match, but "_" may ("Arztbrief_Schmidt").
                r"(?<![^\W_])((?:" + "|".join(re.escape(a).replace(r"\ ", r"\s+") for a in alternatives) + r")(?:s|')?)(?![^\W_])"
            )
            if alternatives
            else None
        )

    def detect(self, text: str) -> list[Span]:
        if self._regex is None:
            return []
        spans = []
        for m in self._regex.finditer(text):
            matched = m.group(1)
            whole = " ".join(matched.split())
            etype = self._type_of.get(whole)
            if etype is None:  # the genitive: "Herr Müllers", "Frau Schulz'"
                base = whole[:-1]
                etype = self._type_of.get(base)
                if etype is None or etype != "PERSON" or len(base) < 4:
                    continue  # "Mais" is not the genitive of the surname Mai
            spans.append(Span(m.start(1), m.end(1), etype, matched, "known"))
        return spans
