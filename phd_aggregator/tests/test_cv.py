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


def test_pdf_without_parser_is_actionable():
    if _pdf_parser_present():
        pytest.skip("a PDF parser is installed — guard path not exercised")
    with pytest.raises(CvParseError) as exc:
        extract_cv_text("cv.pdf", b"%PDF-1.4\n" + b"stuff " * 20)
    msg = str(exc.value)
    assert "pdfplumber" in msg or "PyMuPDF" in msg


def test_docx_without_parser_is_actionable():
    try:
        import docx  # noqa: F401
        pytest.skip("python-docx installed — guard path not exercised")
    except ImportError:
        pass
    with pytest.raises(CvParseError) as exc:
        extract_cv_text("cv.docx", b"PK\x03\x04" + b"x" * 40)
    assert "python-docx" in str(exc.value)


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
