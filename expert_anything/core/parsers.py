"""Source parsers: turn an uploaded file or pasted text into raw text.

Reuses the robust text extraction from the legacy MVP (EPUB/PDF/Markdown)
and adds plain-text / HTML fallbacks. PDF uses pypdf when available.
"""
from __future__ import annotations

import base64
import re
import zipfile
from pathlib import Path


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


def extract_from_base64(content_b64: str, filename: str) -> str:
    return extract_from_bytes(base64.b64decode(content_b64), filename)


def _extract_epub(raw: bytes) -> str:
    chunks: list[str] = []
    with zipfile.ZipFile(__import__("io").BytesIO(raw)) as book:
        for name in book.namelist():
            if name.lower().endswith((".xhtml", ".html", ".htm")):
                chunks.append(
                    clean_text(book.read(name).decode("utf-8", errors="ignore"))
                )
    return "\n\n".join(chunks)


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
