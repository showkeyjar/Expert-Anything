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


def _extract_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""
    try:
        reader = PdfReader(__import__("io").BytesIO(raw))
        pages = [(p.extract_text() or "") for p in reader.pages]
        text = "\n\n".join(pages)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    except Exception:
        return ""


def title_from(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        generic = ("目录" in line and ("内容简介" in line or "第一章" in line)) or re.fullmatch(
            r"[·.\s\d-]+", line or ""
        )
        if line and not generic and len(line) <= 100:
            return line[:100]
    return Path(fallback).stem.replace("_", " ").replace("-", " ").title()
