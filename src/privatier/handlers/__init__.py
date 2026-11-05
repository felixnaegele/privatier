"""File-type handlers.

Each handler knows how to read one kind of file, pass its text through a
Transformer, and write the result. To support a new file type later (an
add-on), write a new handler class and add it to HANDLERS below.
"""

from __future__ import annotations

from pathlib import Path

from .base import Handler
from .csv_handler import CsvHandler
from .docx_handler import DocxHandler
from .excel_handler import ExcelHandler
from .pdf_handler import PdfHandler
from .spss_handler import SpssHandler
from .text_handler import TextHandler

HANDLERS: list[Handler] = [
    CsvHandler(),
    ExcelHandler(),
    SpssHandler(),
    DocxHandler(),
    PdfHandler(),
    TextHandler(),
]


def handler_for(path: Path) -> Handler | None:
    suffix = path.suffix.lower()
    for handler in HANDLERS:
        if suffix in handler.extensions:
            return handler
    return None


__all__ = ["HANDLERS", "Handler", "handler_for"]
