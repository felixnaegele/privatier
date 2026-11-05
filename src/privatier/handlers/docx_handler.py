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


def _transform_paragraphs(root, t: Transformer) -> None:
    for p in root.iter(_W_P):
        for tag in _TEXT_TAGS:
            nodes = [n for n in p.iter(tag) if next(n.iterancestors(_W_P), None) is p]
            if not nodes:
                continue
            joined = "".join(n.text or "" for n in nodes)
            new = t.text(joined)
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

        props = doc.core_properties
        props.author = ""
        props.last_modified_by = ""
        props.title = t.text(props.title or "")
        props.subject = t.text(props.subject or "")
        props.comments = t.text(props.comments or "")
        props.keywords = t.text(props.keywords or "")
        if dst is not None:
            doc.save(str(dst))
