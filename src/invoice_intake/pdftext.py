"""Text out of a PDF. Scanned (image-only) PDFs have no text layer; they are
reported as such rather than silently extracting nothing."""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


class NoTextLayer(ValueError):
    pass


def pdf_text(path: Path | str) -> str:
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if len(text.strip()) < 20:
        raise NoTextLayer(f"{Path(path).name}: no text layer (a scan?); OCR it first or use a vision model")
    return text
