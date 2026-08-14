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
    """Raised with a user-facing message when a CV cannot be parsed.

    ``can_paste_instead`` marks the failures where the paste-text path is a
    working way forward, so the UI can offer it automatically instead of
    leaving the user at a dead end.
    """

    def __init__(self, message: str, *, can_paste_instead: bool = True,
                 reason: str = "unreadable"):
        super().__init__(message)
        self.can_paste_instead = can_paste_instead
        # Machine-readable cause so the UI (and the tests) can distinguish
        # "no parser installed" from "this PDF is a scan" from "file is empty".
        self.reason = reason


def parser_support() -> dict[str, bool]:
    """Which CV formats this installation can actually read, right now.

    TXT always works. PDF and DOCX depend on libraries that are declared in
    requirements.txt but may be absent from the interpreter actually serving
    the API — the exact situation that produced "PDF support needs a parser"
    on a machine whose venv had pdfplumber but whose API ran under a different
    Python. Reported at startup and surfaced to the UI so the limitation is
    visible before a user picks a file, not after.
    """
    def _has(module: str) -> bool:
        import importlib.util
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            return False

    return {
        "txt": True,
        "pdf": _has("pdfplumber") or _has("fitz"),
        "docx": _has("docx"),
    }


def extract_cv_text(filename: str, data: bytes) -> str:
    """Return the plain text of a CV given its ``filename`` and raw ``bytes``.

    Supports ``.txt`` / ``.md``, ``.pdf`` and ``.docx``. Raises
    :class:`CvParseError` — with a message safe to show the user — on an empty
    or oversized file, an unsupported type, a missing parser dependency, or a
    result too short to be real text (e.g. a scanned/image PDF)."""
    if not data:
        raise CvParseError("The uploaded file is empty.", reason="empty_file")
    if len(data) > MAX_CV_BYTES:
        raise CvParseError(
            f"File too large (max {MAX_CV_BYTES // (1024 * 1024)} MB).",
            reason="too_large")

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
            f"Unsupported file type '.{ext}'. Upload a PDF, DOCX or TXT file, "
            "or paste the text.", reason="unsupported_type")

    text = _clean(text)
    if len(text) < _MIN_USEFUL_CHARS:
        raise CvParseError(
            "That file contains no readable text — a scanned PDF is an image, "
            "not text. Paste your CV text instead.", reason="no_text")
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
            # Never instruct the user to install anything: they may not own
            # the machine, and the paste path works right now.
            raise CvParseError(
                "This installation cannot read PDF files. Paste your CV text "
                "instead — it works just as well.",
                reason="no_pdf_parser")
        try:
            doc = fitz.open(stream=data, filetype="pdf")
            return "\n".join(page.get_text() for page in doc)
        except Exception as exc:  # corrupt / encrypted PDF
            raise CvParseError(f"Could not read the PDF: {exc}",
                               reason="corrupt")
    try:
        parts = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except Exception as exc:  # corrupt / encrypted PDF
        raise CvParseError(f"Could not read the PDF: {exc}", reason="corrupt")


def _from_docx(data: bytes) -> str:
    try:
        import docx  # python-docx
    except ImportError:
        raise CvParseError(
            "This installation cannot read Word files. Paste your CV text "
            "instead — it works just as well.",
            reason="no_docx_parser")
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # not a real .docx
        raise CvParseError(f"Could not read the DOCX file: {exc}",
                           reason="corrupt")
    return "\n".join(p.text for p in document.paragraphs)
