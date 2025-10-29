
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def app_module():
    import app.app as app_module

    app_module.app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret",
    )

    return app_module


def test_submission_closes_db_resources_when_pdf_generation_fails(
    app_module, monkeypatch, tmp_path
):
    conn = MagicMock()
    cur = MagicMock()

    conn.cursor.return_value = cur

    # No existing application, then return the newly inserted ID.
    cur.fetchone.side_effect = [(0,), (101,), (0,)]

    monkeypatch.setattr(app_module, "get_db", lambda: conn)

    def fail_pdf_generation(*args):
        raise RuntimeError("PDF generation failed")

    monkeypatch.setattr(
        app_module,
        "generate_acknowledgment",
        fail_pdf_generation,
    )
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path))

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["verified_mobile"] = "9876543210"
            session["form_data"] = {
                "applicant_name": "Test User",
                "village": "Test Village",
                "block": "Test Block",
                "gender": "Male",
                "marital_status": "Married",
                "bank_account": "123456789",
                "ifsc": "TEST0001234",
                "dob": "01/01/1950",
            }
            session["doc_path"] = "test-document.pdf"

        with pytest.raises(RuntimeError, match="PDF generation failed"):
            client.post("/declaration")


    cur.close.assert_called_once()
    conn.close.assert_called_once()
