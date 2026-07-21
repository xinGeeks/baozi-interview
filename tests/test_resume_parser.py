"""resume_parser.py 单元测试。"""
from io import BytesIO

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from resume_parser import ResumeParseError, parse_pdf_resume


def _make_pdf_bytes(pages: list[str]) -> bytes:
    """用 reportlab 构造多页 PDF 字节流(供测试用 fixture,文本可被 pypdf 抽取)。"""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for content in pages:
        c.drawString(50, 750, content)
        c.showPage()
    c.save()
    return buf.getvalue()


def test_parse_pdf_resume_happy_path():
    pdf = _make_pdf_bytes(["John Doe, Backend Engineer", "5 years Python experience"])
    text = parse_pdf_resume(pdf)
    assert "John Doe" in text
    assert "Backend Engineer" in text
    assert "Python" in text


def test_parse_pdf_resume_empty_file():
    with pytest.raises(ResumeParseError, match="文件为空"):
        parse_pdf_resume(b"")


def test_parse_pdf_resume_not_pdf():
    with pytest.raises(ResumeParseError, match="无法识别为 PDF"):
        parse_pdf_resume(b"this is just plain text, not a pdf")


def test_parse_pdf_resume_corrupt_pdf():
    """PDF 头正确但内容损坏。"""
    bad = b"%PDF-1.4\nthis is not valid pdf content\n%%EOF"
    with pytest.raises(ResumeParseError):
        parse_pdf_resume(bad)


def test_parse_pdf_resume_multiple_pages_joined():
    pdf = _make_pdf_bytes(["page one content", "page two content"])
    text = parse_pdf_resume(pdf)
    assert "page one content" in text
    assert "page two content" in text


def test_parse_pdf_resume_returns_str():
    pdf = _make_pdf_bytes(["any text"])
    result = parse_pdf_resume(pdf)
    assert isinstance(result, str)
    assert len(result) > 0
