"""core.cv — extract plain text from an uploaded CV (Track 2B).

Local-only by design: parsing happens in this process, the file is never sent
to a third party and never written to disk. TXT needs no extra dependency; PDF
needs ``pdfplumber`` (or PyMuPDF) and DOCX needs ``python-docx`` — each is
imported lazily and, when missing, raises a clear, actionable error instead of
a silent no-op.
"""

from __future__ import annotations

import io
import re

# Guard against decompression bombs / accidental huge uploads.
MAX_CV_BYTES = 10 * 1024 * 1024  # 10 MB
_MIN_USEFUL_CHARS = 20


class CvParseError(ValueError):
    """Raised with a user-facing message when a CV cannot be parsed."""


def extract_cv_text(filename: str, data: bytes) -> str:
    """Return the plain text of a CV given its ``filename`` and raw ``bytes``.

    Supports ``.txt`` / ``.md``, ``.pdf`` and ``.docx``. Raises
    :class:`CvParseError` — with a message safe to show the user — on an empty
    or oversized file, an unsupported type, a missing parser dependency, or a
    result too short to be real text (e.g. a scanned/image PDF)."""
    if not data:
        raise CvParseError("The uploaded file is empty.")
    if len(data) > MAX_CV_BYTES:
        raise CvParseError(
            f"File too large (max {MAX_CV_BYTES // (1024 * 1024)} MB).")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # Content sniffing wins over a misleading extension.
    if ext == "pdf" or data[:5] == b"%PDF-":
        text = _from_pdf(data)
    elif ext == "docx" or (data[:2] == b"PK" and ext == ""):
        text = _from_docx(data)
    elif ext in ("txt", "md", "text", ""):
        text = _from_txt(data)
    else:
        raise CvParseError(
            f"Unsupported file type '.{ext}'. Upload a PDF, DOCX or TXT file "
            "(or paste the text).")

    text = _clean(text)
    if len(text) < _MIN_USEFUL_CHARS:
        raise CvParseError(
            "Could not read usable text from the file. If it is a scanned PDF "
            "(an image), paste the text instead — OCR is not supported.")
    return text


def _clean(text: str) -> str:
    """Normalise whitespace while keeping paragraph structure."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _from_txt(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _from_pdf(data: bytes) -> str:
    try:
        import pdfplumber
    except ImportError:
        try:
            import fitz  # PyMuPDF, an alternative backend
        except ImportError:
            raise CvParseError(
                "PDF support needs a parser. Install one:  "
                "pip install pdfplumber   (or PyMuPDF). Meanwhile you can paste "
                "the CV text instead.")
        try:
            doc = fitz.open(stream=data, filetype="pdf")
            return "\n".join(page.get_text() for page in doc)
        except Exception as exc:  # corrupt / encrypted PDF
            raise CvParseError(f"Could not read the PDF: {exc}")
    try:
        parts = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except Exception as exc:  # corrupt / encrypted PDF
        raise CvParseError(f"Could not read the PDF: {exc}")


def _from_docx(data: bytes) -> str:
    try:
        import docx  # python-docx
    except ImportError:
        raise CvParseError(
            "DOCX support needs python-docx. Install it:  "
            "pip install python-docx. Meanwhile you can paste the CV text "
            "instead.")
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # not a real .docx
        raise CvParseError(f"Could not read the DOCX file: {exc}")
    return "\n".join(p.text for p in document.paragraphs)
