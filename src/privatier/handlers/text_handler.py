from __future__ import annotations

from pathlib import Path

from ..transform import Transformer
from .base import SameNameMixin


def read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


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
