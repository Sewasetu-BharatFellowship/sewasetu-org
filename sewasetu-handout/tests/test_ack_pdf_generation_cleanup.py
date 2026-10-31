import pytest
from unittest.mock import MagicMock


@pytest.fixture
def app_module(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "test-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-password")

    import app.app as app_module

    app_module.app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret",
    )

    return app_module



def test_ack_pdf_closes_db_resources_when_pdf_generation_fails(
    app_module, monkeypatch
):
    ownership_conn = MagicMock()
    ownership_cur = MagicMock()
    ownership_conn.cursor.return_value = ownership_cur
    ownership_cur.fetchone.return_value = ("9876543210",)

    pdf_conn = MagicMock()
    pdf_cur = MagicMock()
    pdf_conn.cursor.return_value = pdf_cur

    connections = iter([ownership_conn, pdf_conn])
    monkeypatch.setattr(
        app_module, "get_db", lambda: next(connections)
    )

    monkeypatch.setattr(
        app_module,
        "generate_acknowledgment",
        MagicMock(side_effect=RuntimeError("PDF generation failed")),
    )
    monkeypatch.setattr(app_module.os.path, "exists", lambda path: False)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["logged_in"] = True
            session["admin"] = True

        with pytest.raises(RuntimeError, match="PDF generation failed"):
            client.get("/ack/1.pdf")

    ownership_cur.close.assert_called_once()
    ownership_conn.close.assert_called_once()

    pdf_cur.close.assert_called_once()
    pdf_conn.close.assert_called_once()