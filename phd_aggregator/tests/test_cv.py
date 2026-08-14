"""tests.test_cv — CV text extraction (Track 2B).

TXT and all the error/guard paths run everywhere. The PDF/DOCX *round-trip*
tests require the optional parsers and are skipped when they are absent
(``pip install pdfplumber python-docx`` to exercise them); the *missing-parser*
guard tests assert the actionable install message instead.
"""

from __future__ import annotations

import io

import pytest

from core.cv import MAX_CV_BYTES, CvParseError, extract_cv_text


def test_txt_extraction_keeps_content():
    text = extract_cv_text(
        "cv.txt",
        b"I am a PhD student in astronomy working on the interstellar medium "
        b"with radio interferometry (LOFAR). I use Python.")
    assert "interstellar medium" in text
    assert "LOFAR" in text


def test_empty_file_errors():
    with pytest.raises(CvParseError):
        extract_cv_text("cv.txt", b"")


def test_too_short_errors():
    with pytest.raises(CvParseError):
        extract_cv_text("cv.txt", b"hi")


def test_unsupported_type_errors():
    with pytest.raises(CvParseError) as exc:
        extract_cv_text("cv.rtf", b"some plausible cv text " * 5)
    assert "Unsupported" in str(exc.value)


def test_oversized_errors():
    with pytest.raises(CvParseError):
        extract_cv_text("cv.txt", b"x" * (MAX_CV_BYTES + 1))


def _pdf_parser_present() -> bool:
    for mod in ("pdfplumber", "fitz"):
        try:
            __import__(mod)
            return True
        except ImportError:
            continue
    return False


def _block_imports(monkeypatch, *blocked):
    """Make the named modules un-importable, so the missing-parser guard is
    exercised on EVERY machine — including CI, where the parsers ARE present.
    Skipping the test there left the degradation path untested."""
    import builtins
    real = builtins.__import__

    def fake(name, *a, **kw):
        if name in blocked:
            raise ImportError(f"blocked for test: {name}")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake)


def test_pdf_without_parser_degrades_to_pasting(monkeypatch):
    """No parser must NEVER tell the user to run pip — they may not own the
    machine, and pasting the text works right now."""
    _block_imports(monkeypatch, "pdfplumber", "fitz")
    with pytest.raises(CvParseError) as exc:
        extract_cv_text("cv.pdf", b"%PDF-1.4\n" + b"stuff " * 20)
    msg = str(exc.value)
    assert "pip install" not in msg.lower()
    assert "paste" in msg.lower()
    assert exc.value.reason == "no_pdf_parser"
    assert exc.value.can_paste_instead is True


def test_docx_without_parser_degrades_to_pasting(monkeypatch):
    _block_imports(monkeypatch, "docx")
    with pytest.raises(CvParseError) as exc:
        extract_cv_text("cv.docx", b"PK\x03\x04" + b"x" * 40)
    msg = str(exc.value)
    assert "pip install" not in msg.lower()
    assert "paste" in msg.lower()
    assert exc.value.reason == "no_docx_parser"


def test_no_error_message_ever_tells_the_user_to_install_something():
    """A blanket guard over the module's user-facing copy."""
    import inspect

    import core.cv as cv_mod
    source = inspect.getsource(cv_mod)
    assert "pip install" not in source.lower()


def test_parser_support_reports_what_this_install_can_read():
    from core.cv import parser_support
    support = parser_support()
    assert support["txt"] is True          # always, no dependency
    assert set(support) == {"txt", "pdf", "docx"}
    assert all(isinstance(v, bool) for v in support.values())


def test_docx_roundtrip_when_available():
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("I research the interstellar medium with radio interferometry.")
    d.add_paragraph("Tools: Python, LOFAR.")
    buf = io.BytesIO()
    d.save(buf)
    text = extract_cv_text("cv.docx", buf.getvalue())
    assert "interstellar medium" in text
    assert "LOFAR" in text
