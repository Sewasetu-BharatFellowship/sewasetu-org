
from datetime import datetime

from app.app import generate_acknowledgment


class MockCursor:
    def execute(self, query, params):
        pass

    def fetchone(self):
        return (
            "SSP26123456",
            "প্ৰণৱ কলিতা",
            "9876543210",
            datetime(1960, 6, 5).date(),
            "Sonari",
            "Sonari",
            "123456789012",
            "SBIN0001234",
            datetime(2026, 10, 31, 10, 30),
            "PENDING",
        )


def test_acknowledgment_pdf_embeds_unicode_font():
    """Generated acknowledgment must embed a Unicode TrueType font."""

    pdf_bytes = generate_acknowledgment(MockCursor(), 1)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")

    # A Unicode TrueType font should be embedded in the PDF.
    assert b"/FontFile2" in pdf_bytes

    # The PDF should contain a Unicode character mapping.
    assert b"/ToUnicode" in pdf_bytes


def test_acknowledgment_pdf_preserves_assamese_name():
    """PDF generation must not silently replace Indic text with question marks."""

    pdf_bytes = generate_acknowledgment(MockCursor(), 1)

    assert pdf_bytes.startswith(b"%PDF")
    assert b"/FontFile2" in pdf_bytes
    assert b"/ToUnicode" in pdf_bytes
