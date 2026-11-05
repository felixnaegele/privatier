from __future__ import annotations

from pathlib import Path

from ..transform import Transformer
from .base import SameNameMixin


class NotPlainTextError(Exception):
    pass


def _encodings_to_try(raw: bytes) -> list[str]:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return ["utf-16"]
    if raw.count(b"\x00") > len(raw) / 4:  # UTF-16 without a mark: every other byte is empty
        sample = raw[:2000]
        little = sample[1::2].count(0) >= sample[0::2].count(0)
        return ["utf-16-le" if little else "utf-16-be"]
    return ["utf-8-sig", "cp1252", "latin-1"]


def read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in _encodings_to_try(raw):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" in text:
            break
        return text, encoding
    # Misread text would pass through unchecked, so it is reported, and never copied.
    raise NotPlainTextError("This file could not be read as text, so it was not processed.")


class TextHandler(SameNameMixin):
    name = "text"
    extensions = (
        ".txt", ".md", ".json", ".xml", ".html", ".htm", ".log", ".tex",
        ".yaml", ".yml", ".r", ".rmd", ".qmd", ".py", ".sql", ".do", ".sps",
    )

    def process(self, src: Path, dst: Path | None, t: Transformer) -> None:
        text, encoding = read_text(src)
        result = t.text(text)
        if dst is not None:
            dst.write_text(result, encoding="utf-8" if encoding == "utf-8-sig" else encoding)
