"""Consistent pseudonyms: the same real value always gets the same token.

"Max Müller" becomes PERSON_0001 in every file of the project, just like a
subject ID in a clinical trial. The table that links tokens back to real
values is stored only in the encrypted key file (vault.py).
"""

from __future__ import annotations

import re

from .detect.base import ENTITY_TYPES, Span

TOKEN_RE = re.compile(rf"\b({'|'.join(ENTITY_TYPES)})[ _-]?(\d{{4,}})\b", re.IGNORECASE)

# Types whose real values are searched for again in every other file.
_PROPAGATE = {"PERSON", "ORG", "LOCATION", "ADDRESS", "ID", "EMAIL", "PHONE", "IBAN"}
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

    # -- assigning tokens ------------------------------------------------------
    def token_for(self, entity_type: str, value: str) -> str:
        key = (entity_type, _normalise(entity_type, value))
        token = self._key_to_token.get(key)
        if token is None:
            self._counters[entity_type] += 1
            token = f"{entity_type}_{self._counters[entity_type]:04d}"
            self._key_to_token[key] = token
            self._token_to_original[token] = " ".join(str(value).split())
            self._token_type[token] = entity_type
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
            ]
        }

    @classmethod
    def from_dict(cls, data: dict) -> Pseudonymizer:
        p = cls()
        for e in data["entries"]:
            token, etype, original = e["token"], e["type"], e["original"]
            p._key_to_token[(etype, _normalise(etype, original))] = token
            p._token_to_original[token] = original
            p._token_type[token] = etype
            num = int(token.rsplit("_", 1)[1])
            p._counters[etype] = max(p._counters.get(etype, 0), num)
        return p


def _worth_propagating(value: str) -> bool:
    v = value.strip()
    if v.isdigit():
        return len(v) >= 5  # short numbers like "12" would match everywhere
    return len(v) >= 3


class KnownValueDetector:
    """Finds every value already identified anywhere in the project."""

    name = "known"

    def __init__(self, pseudonymizer: Pseudonymizer):
        values = pseudonymizer.known_values()
        self._type_of: dict[str, str] = {}
        alternatives: list[str] = []
        for etype, value in values:
            for variant in {value, value.upper(), value.title()}:
                if variant not in self._type_of:
                    self._type_of[variant] = etype
                    alternatives.append(variant)
        alternatives.sort(key=len, reverse=True)
        self._regex = (
            re.compile(
                # Boundaries: a letter or digit may not touch the match, but "_" may ("Arztbrief_Schmidt").
                r"(?<![^\W_])(" + "|".join(re.escape(a).replace(r"\ ", r"\s+") for a in alternatives) + r")(?![^\W_])"
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
            etype = self._type_of.get(matched) or self._type_of.get(" ".join(matched.split()), "PERSON")
            spans.append(Span(m.start(1), m.end(1), etype, matched, "known"))
        return spans
