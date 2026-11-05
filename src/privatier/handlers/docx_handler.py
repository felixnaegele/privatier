"""Word documents (.docx).

We work on the document's XML directly, so nothing is missed: body text,
tables, text boxes, headers, footers, footnotes, endnotes, comments, tracked
changes (including deleted text, which Word keeps in the file), hyperlink
targets and author names.

Formatting is preserved, except that within a paragraph where something was
replaced, mixed formatting (e.g. one bold word) may be simplified.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from ..tables import classify_header
from ..transform import Transformer

_TEXT_PART_SUFFIXES = (
    "document.main+xml",
    "header+xml",
    "footer+xml",
    "footnotes+xml",
    "endnotes+xml",
    "comments+xml",
    "template.main+xml",
    "document.macroEnabled.main+xml",
)
_W_P = qn("w:p")
_TEXT_TAGS = (qn("w:t"), qn("w:delText"))
_PERSON_ATTRS = (qn("w:author"), qn("w:initials"))
_W_TR, _W_TC = qn("w:tr"), qn("w:tc")


def _cell_text(cell) -> str:
    return "".join(n.text or "" for n in cell.iter(qn("w:t"))).strip()


def _labelled_paragraphs(root) -> dict:
    """In a table, the cell next to or below "Fallnummer" holds a case number, whatever it looks like.

    Forms have the label on the left, lists have a header row on top. Labels themselves are never values.
    """
    labelled = {}
    for table in root.iter(qn("w:tbl")):
        rows = [[c for c in tr if c.tag == _W_TC] for tr in table if tr.tag == _W_TR]
        if not rows:
            continue
        heads = [classify_header(_cell_text(c)) for c in rows[0]]
        header_row = len(rows[0]) >= 3 and sum(1 for h in heads if h) >= 2
        for r, row in enumerate(rows):
            for i, cell in enumerate(row):
                if header_row:
                    category = heads[i] if r > 0 and i < len(heads) else None
                else:
                    category = classify_header(_cell_text(row[i - 1])) if i % 2 == 1 else None
                if category is not None:
                    for p in cell.iter(_W_P):
                        labelled[p] = category
    return labelled


def _transform_paragraphs(root, t: Transformer) -> None:
    labelled = _labelled_paragraphs(root)
    for p in root.iter(_W_P):
        for tag in _TEXT_TAGS:
            nodes = [n for n in p.iter(tag) if next(n.iterancestors(_W_P), None) is p]
            if not nodes:
                continue
            joined = "".join(n.text or "" for n in nodes)
            new = t.labelled(labelled[p], joined) if p in labelled else t.text(joined)
            if new != joined:
                nodes[0].text = new
                nodes[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                for n in nodes[1:]:
                    n.text = ""
    for el in root.iter():
        for attr in _PERSON_ATTRS:
            if attr in el.attrib:
                el.set(attr, "")


class DocxHandler:
    name = "docx"
    extensions = (".docx", ".docm")

    def output_name(self, src: Path) -> str:
        return src.name

    def process(self, src: Path, dst: Path | None, t: Transformer) -> None:
        doc = Document(str(src))
        for part in doc.part.package.iter_parts():
            if not str(part.content_type).endswith(_TEXT_PART_SUFFIXES):
                continue
            element = getattr(part, "_element", None)
            if element is not None:
                _transform_paragraphs(element, t)
            else:  # parts python-docx does not parse itself (e.g. footnotes)
                root = etree.fromstring(part.blob)
                _transform_paragraphs(root, t)
                part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            for rel in part.rels.values():
                if rel.is_external:
                    rel._target = t.text(rel._target)

        pictures = sum(1 for part in doc.part.package.iter_parts() if str(part.content_type).startswith("image/"))
        if pictures:
            t.note_unchecked(f"{pictures} picture(s) in this document were kept and cannot be checked")
        props = doc.core_properties
        props.author = ""
        props.last_modified_by = ""
        props.title = t.text(props.title or "")
        props.subject = t.text(props.subject or "")
        props.comments = t.text(props.comments or "")
        props.keywords = t.text(props.keywords or "")
        if dst is not None:
            doc.save(str(dst))
