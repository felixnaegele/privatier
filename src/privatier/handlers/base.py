from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..transform import Transformer


class Handler(Protocol):
    name: str
    extensions: tuple[str, ...]

    def output_name(self, src: Path) -> str:
        """File name of the result (most handlers keep the original name)."""
        ...

    def process(self, src: Path, dst: Path | None, t: Transformer) -> None:
        """Read src, transform it, and write to dst. dst=None means read-only (first pass)."""
        ...


class SameNameMixin:
    def output_name(self, src: Path) -> str:
        return src.name
