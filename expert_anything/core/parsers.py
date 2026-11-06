"""Source parsers: turn an uploaded file or pasted text into raw text.

Reuses the robust text extraction from the legacy MVP (EPUB/PDF/Markdown)
and adds plain-text / HTML fallbacks. PDF uses pypdf when available.
"""
from __future__ import annotations

import html
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from posixpath import normpath
from urllib.parse import unquote
from xml.etree import ElementTree


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def extract_from_bytes(raw: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".epub":
        return _extract_epub(raw)
    if suffix == ".pdf":
        return _extract_pdf(raw)
    if suffix in (".docx", ".docm"):
        return _extract_docx(raw)
    if suffix in (".html", ".htm"):
        return clean_text(raw.decode("utf-8", errors="ignore"))
    return raw.decode("utf-8", errors="ignore")


def _extract_epub(raw: bytes) -> str:
    """Extract readable EPUB text in the book's declared reading order.

    An EPUB is a zip archive, not a bag of independent HTML files.  The old
    implementation iterated the archive order and removed all markup in one
    pass.  That loses paragraph boundaries and can put the cover, navigation,
    footnotes and chapters in an arbitrary order.  Both the extraction model
    and the UI depend on those boundaries, so use ``container.xml``/OPF spine
    when available and preserve block-level structure.
    """
    import io

    with zipfile.ZipFile(io.BytesIO(raw)) as book:
        names = set(book.namelist())
        opf_name = _epub_opf_path(book)
        ordered: list[str] = []
        excluded: set[str] = set()
        if opf_name:
            try:
                opf = ElementTree.fromstring(book.read(opf_name))
                manifest: dict[str, tuple[str, str]] = {}
                for item in opf.iter():
                    if _local_name(item.tag) != "item":
                        continue
                    item_id = item.attrib.get("id", "")
                    href = item.attrib.get("href", "")
                    if not item_id or not href:
                        continue
                    path = _epub_join(opf_name, href)
                    manifest[item_id] = (path, item.attrib.get("properties", ""))
                    if "nav" in item.attrib.get("properties", "").split():
                        excluded.add(path)
                for itemref in opf.iter():
                    if _local_name(itemref.tag) != "itemref":
                        continue
                    path_props = manifest.get(itemref.attrib.get("idref", ""))
                    if path_props and path_props[0] not in excluded:
                        ordered.append(path_props[0])
            except (ElementTree.ParseError, KeyError, ValueError):
                ordered = []

        # Some producer tools omit a valid spine. Keep a deterministic,
        # conservative fallback while excluding obvious navigation documents.
        if not ordered:
            ordered = sorted(
                name for name in names
                if name.lower().endswith((".xhtml", ".html", ".htm"))
                and not re.search(r"(^|/)(nav|toc|contents?)\.(x?html?)$", name, re.I)
            )

        chunks: list[str] = []
        for name in ordered:
            if name not in names or name in excluded:
                continue
            parsed = _extract_html_blocks(
                book.read(name).decode("utf-8", errors="ignore")
            )
            if parsed:
                chunks.append(parsed)
        return "\n\n".join(chunks)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _epub_opf_path(book: zipfile.ZipFile) -> str:
    try:
        root = ElementTree.fromstring(book.read("META-INF/container.xml"))
        for node in root.iter():
            if _local_name(node.tag) == "rootfile" and node.attrib.get("full-path"):
                return node.attrib["full-path"]
    except (KeyError, ElementTree.ParseError):
        pass
    return ""


def _epub_join(opf_name: str, href: str) -> str:
    # OPF hrefs may contain URL escaping and fragment anchors. Zip member names
    # use POSIX separators regardless of the host OS.
    href = unquote(html.unescape(href).split("#", 1)[0])
    base = opf_name.rsplit("/", 1)[0] if "/" in opf_name else ""
    return normpath(f"{base}/{href}").lstrip("./")


class _ReadableHTML(HTMLParser):
    """Small EPUB XHTML reader that keeps block and heading boundaries."""

    _BLOCKS = {
        "address", "article", "aside", "blockquote", "br", "dd", "div",
        "dl", "dt", "figcaption", "figure", "footer", "h1", "h2", "h3",
        "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol",
        "p", "pre", "section", "table", "td", "th", "tr", "ul",
    }
    _SKIP = {"head", "nav", "script", "style", "svg", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[tuple[str, bool]] = []
        self._skip = 0
        self._line: list[str] = []
        self._heading = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in self._BLOCKS:
            self._flush()
            self._heading = tag in {"h1", "h2", "h3", "h4", "h5", "h6"}

    def handle_startendtag(self, tag, attrs):
        if tag.lower() in self._BLOCKS and not self._skip:
            self._flush()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if not self._skip and tag in self._BLOCKS:
            self._flush()
            self._heading = False

    def handle_data(self, data):
        if self._skip:
            return
        value = re.sub(r"\s+", " ", data).strip()
        if value:
            self._line.append(value)

    def _flush(self):
        value = " ".join(self._line).strip()
        self._line.clear()
        if value and (not self.parts or self.parts[-1][0] != value):
            self.parts.append((value, self._heading))


def _extract_html_blocks(source: str) -> str:
    parser = _ReadableHTML()
    try:
        parser.feed(source)
        parser.close()
    except Exception:
        # Malformed XHTML should not abort the complete import.
        return clean_text(source)
    parser._flush()
    # Keep heading blocks visually unobtrusive but structurally detectable by
    # downstream deterministic extraction: ordinary blocks use one newline,
    # semantic h1-h6 blocks get a blank line around them.
    out: list[str] = []
    for value, is_heading in parser.parts:
        out.append(f"\n{value}\n" if is_heading else value)
    return "\n".join(out).strip()


def _extract_docx(raw: bytes) -> str:
    """Extract text from a .docx (OOXML zip) without external deps.

    Reads word/document.xml, splits on paragraph boundaries and strips all
    tags via clean_text(). Tables and headers are ignored (document.xml body
    only) — good enough for learning-material ingestion.
    """
    try:
        import io
        with zipfile.ZipFile(io.BytesIO(raw)) as book:
            xml = book.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception:
        return ""
    paragraphs = re.split(r"</w:p>", xml)
    out: list[str] = []
    for para in paragraphs:
        text = clean_text(para)
        if text:
            out.append(text)
    return "\n\n".join(out)


def _pdf_pages(raw: bytes) -> list[str]:
    """Return normalized per-page text for a PDF (empty list on failure)."""
    try:
        from pypdf import PdfReader
        import io
    except Exception:
        return []
    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception:
        return []
    out: list[str] = []
    for pg in pages:
        pg = re.sub(r"[ \t]+", " ", pg)
        pg = re.sub(r"\n{3,}", "\n\n", pg)
        out.append(pg.strip())
    return out


def _extract_pdf(raw: bytes) -> str:
    return "\n\n".join(_pdf_pages(raw)).strip()


def pdf_page_offsets(raw: bytes) -> list[int]:
    """Cumulative character offset of each page start in the joined PDF text.

    page_offsets[i] is the index into source_text where page i begins, so a
    SourceLocation with char_start >= page_offsets[i] and < page_offsets[i+1]
    belongs to page i+1 (1-based). Empty list for non-PDF / parse failure.
    """
    pages = _pdf_pages(raw)
    offsets: list[int] = []
    pos = 0
    for i, pg in enumerate(pages):
        offsets.append(pos)
        pos += len(pg)
        if i < len(pages) - 1:
            pos += len("\n\n")
    return offsets


def title_from(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        generic = ("目录" in line and ("内容简介" in line or "第一章" in line)) or re.fullmatch(
            r"[·.\s\d-]+", line or ""
        )
        if line and not generic and len(line) <= 100:
            return line[:100]
    return Path(fallback).stem.replace("_", " ").replace("-", " ").title()
