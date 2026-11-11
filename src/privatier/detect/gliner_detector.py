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

import importlib.util
import logging
import os
import sys
import warnings
from pathlib import Path

from .base import Span

DEFAULT_MODEL = "urchade/gliner_multi_pii-v1"
TOKENIZER_MODEL = "microsoft/mdeberta-v3-base"  # GLiNER reads its tokenizer from here

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


class AIModelError(RuntimeError):
    pass


def frozen() -> bool:
    """True inside the installed Privatier.app (built with PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def bundled_hub() -> Path | None:
    """Where the installed app keeps the AI model (a Hugging Face cache layout), or None from source."""
    if not frozen():
        return None
    base = Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).resolve().parent)
    return base / "ai" / "hub"


def use_bundled_model() -> None:
    """Inside the installed app: read the model from the app itself and never touch the internet.

    Must run before the AI libraries are imported. From a source checkout this does nothing.
    """
    hub = bundled_hub()
    if hub is None:
        return
    os.environ["HF_HUB_CACHE"] = str(hub)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(hub)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


use_bundled_model()


def _hub_dir() -> Path:
    hub = bundled_hub()
    if hub is not None:
        return hub
    env = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if env:
        return Path(env)
    return Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"


def _snapshot_has(model_name: str, *needed: str) -> bool:
    folder = _hub_dir() / ("models--" + model_name.replace("/", "--"))
    try:
        rev = (folder / "refs" / "main").read_text().strip()
        snaps = [folder / "snapshots" / rev]
    except OSError:
        snaps = sorted((folder / "snapshots").glob("*")) if (folder / "snapshots").is_dir() else []
    return any(all((snap / name).exists() for name in needed) for snap in snaps)


def model_ready() -> bool:
    """The AI add-on can be imported and its model files are on this computer.

    Nothing is downloaded or loaded here, so it is cheap enough to call at startup.
    """
    try:
        if importlib.util.find_spec("gliner") is None:
            return False
    except (ImportError, ValueError):
        return False
    return _snapshot_has(DEFAULT_MODEL, "gliner_config.json", "pytorch_model.bin") and _snapshot_has(
        TOKENIZER_MODEL, "config.json", "spm.model"
    )


def _quiet() -> None:
    """Hide technical warnings from the AI libraries that would only confuse users."""
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=UserWarning)
    logging.getLogger("torch.distributed.elastic").setLevel(logging.ERROR)


def is_available() -> bool:
    try:
        import gliner  # noqa: F401
    except ImportError:
        return False
    return True


def download_model(model_name: str = DEFAULT_MODEL) -> str:
    """Download the model once (the only step that uses the internet)."""
    if frozen():
        raise AIModelError("The AI model is already part of this app and needs no download.")
    _quiet()
    from gliner import GLiNER

    try:
        GLiNER.from_pretrained(model_name)
    except Exception as exc:
        raise AIModelError(f"The AI model could not be set up: {exc}") from exc
    return model_name


def _missing_text(reason: str) -> str:
    if frozen():
        return (
            f"The AI name recognition cannot start: {reason}. The AI model belongs inside the Privatier app, "
            "so the app may be damaged. Please install Privatier again from the disk image, "
            "or switch off the AI option to continue without it."
        )
    return (
        f"{reason[0].upper() + reason[1:]}. Run 'privatier setup-ai' first; "
        "if that does not help, reinstall with: pip install -e \".[ai]\""
    )


class GlinerDetector:
    name = "ner"

    def __init__(self, model_name: str = DEFAULT_MODEL, threshold: float = 0.5):
        use_bundled_model()
        os.environ["HF_HUB_OFFLINE"] = "1"  # never reach out to the internet
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        _quiet()
        try:
            from gliner import GLiNER
        except ImportError as exc:
            raise AIModelError(_missing_text(f"the AI part is not installed ({type(exc).__name__})")) from exc

        try:
            self.model = GLiNER.from_pretrained(model_name, local_files_only=True)
        except Exception as exc:
            raise AIModelError(_missing_text(f"the local AI model could not be loaded ({exc})")) from exc
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
