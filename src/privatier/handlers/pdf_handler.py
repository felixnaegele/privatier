"""PDFs: the text is extracted and written as an anonymised Markdown file.

Rewriting the PDF itself (keeping its layout) is a possible future add-on.
Scanned PDFs (pictures of pages) contain no text; they are skipped with a
warning and never copied, because we cannot check them. OCR could be added
later as an add-on.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from ..transform import Transformer


class NoTextInPdfError(Exception):
    pass


class PdfHandler:
    name = "pdf"
    extensions = (".pdf",)

    def output_name(self, src: Path) -> str:
        return src.name + ".md"  # report.pdf -> report.pdf.md

    def process(self, src: Path, dst: Path | None, t: Transformer) -> None:
        reader = PdfReader(str(src))
        pages = [(page.extract_text() or "") for page in reader.pages]
        if sum(len(p.strip()) for p in pages) < 20 * max(1, len(pages)):
            raise NoTextInPdfError(
                "This PDF contains (almost) no text. It is probably scanned; text recognition (OCR) "
                "is not supported yet, so the file was not processed."
            )
        parts = []
        for number, text in enumerate(pages, start=1):
            parts.append(f"## Page {number}\n\n{t.text(text).strip()}\n")
        if dst is not None:
            dst.write_text("\n".join(parts), encoding="utf-8")
