"""Local AI name recognition with GLiNER (optional layer).

GLiNER is a small transformer model (a few hundred MB) that finds names,
organisations and places in free text, in German, English and other
languages. It runs entirely on the laptop. On Apple Silicon it uses the GPU
(MPS) when available.

The model is downloaded once with `privatier setup-ai`. During anonymisation
Privatier blocks all network access, so the model can only run locally.

Install with:  pip install "privatier[ai]"
"""

from __future__ import annotations

import os

from .base import Span

DEFAULT_MODEL = "urchade/gliner_multi_pii-v1"

# GLiNER label -> Privatier entity type
LABELS = {
    "person": "PERSON",
    "organization": "ORG",
    "hospital": "ORG",
    "city": "LOCATION",
    "location": "LOCATION",
    "street address": "ADDRESS",
    "phone number": "PHONE",
    "email": "EMAIL",
    "date of birth": "DATE",
    "medical record number": "ID",
    "health insurance number": "ID",
    "social security number": "ID",
}

# The model reads about 380 tokens at a time; we split long text into chunks.
_CHUNK_CHARS = 1200
_OVERLAP = 150


def is_available() -> bool:
    try:
        import gliner  # noqa: F401
    except ImportError:
        return False
    return True


def download_model(model_name: str = DEFAULT_MODEL) -> str:
    """Download the model once (the only step that uses the internet)."""
    from gliner import GLiNER

    GLiNER.from_pretrained(model_name)
    return model_name


class GlinerDetector:
    name = "ner"

    def __init__(self, model_name: str = DEFAULT_MODEL, threshold: float = 0.5):
        os.environ["HF_HUB_OFFLINE"] = "1"  # never reach out to the internet
        from gliner import GLiNER

        self.model = GLiNER.from_pretrained(model_name, local_files_only=True)
        try:
            import torch

            if torch.backends.mps.is_available():
                self.model = self.model.to("mps")
        except Exception:
            pass
        self.threshold = threshold
        self.labels = list(LABELS)

    def detect(self, text: str) -> list[Span]:
        if len(text.strip()) < 3:
            return []
        spans: list[Span] = []
        for offset, chunk in _chunks(text):
            for ent in self.model.predict_entities(chunk, self.labels, threshold=self.threshold):
                etype = LABELS.get(ent["label"])
                if not etype:
                    continue
                start, end = offset + ent["start"], offset + ent["end"]
                spans.append(Span(start, end, etype, text[start:end], "ner", float(ent["score"])))
        return spans


def _chunks(text: str):
    if len(text) <= _CHUNK_CHARS:
        yield 0, text
        return
    pos = 0
    while pos < len(text):
        end = min(len(text), pos + _CHUNK_CHARS)
        if end < len(text):  # cut at whitespace so words stay whole
            cut = text.rfind(" ", pos + _CHUNK_CHARS // 2, end)
            end = cut if cut > 0 else end
        yield pos, text[pos:end]
        if end >= len(text):
            break
        pos = max(end - _OVERLAP, pos + 1)
        while pos < len(text) and not text[pos - 1].isspace():
            pos += 1
