"""Shared building blocks for all detectors.

A detector receives a piece of text and returns the places (spans) where it
found sensitive information. Every detector follows the same small interface,
so new ones (e.g. a local LLM reviewer) can be added later without touching
the rest of the program.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# Entity types Privatier knows about. Each becomes a token prefix, e.g. PERSON_0001.
ENTITY_TYPES = (
    "PERSON",
    "ORG",
    "LOCATION",
    "ADDRESS",
    "DATE",
    "ID",
    "EMAIL",
    "PHONE",
    "IBAN",
)

# When two detections overlap and have the same length, the higher priority wins.
PRIORITY = {"known": 3, "pattern": 2, "ner": 1, "llm": 0}


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    entity_type: str
    text: str
    source: str  # "pattern", "known", "ner", ...
    score: float = 1.0


class Detector(Protocol):
    name: str

    def detect(self, text: str) -> list[Span]: ...


def resolve_overlaps(spans: list[Span]) -> list[Span]:
    """Keep a non-overlapping set of spans, preferring longer and higher-priority ones."""
    ranked = sorted(
        spans,
        key=lambda s: (-(s.end - s.start), -PRIORITY.get(s.source, 0), s.start),
    )
    chosen: list[Span] = []
    for span in ranked:
        if all(span.end <= c.start or span.start >= c.end for c in chosen):
            chosen.append(span)
    return sorted(chosen, key=lambda s: s.start)
