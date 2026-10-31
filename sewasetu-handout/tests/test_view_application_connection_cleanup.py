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


def test_view_application_closes_db_resources_when_query_fails(
    app_module, monkeypatch
):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.execute.side_effect = RuntimeError("Database query failed")

    monkeypatch.setattr(app_module, "get_db", lambda: conn)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["logged_in"] = True
            session["portal_mobile"] = "9876543210"

        with pytest.raises(RuntimeError, match="Database query failed"):
            client.get("/application/1")

    cur.close.assert_called_once()
    conn.close.assert_called_once()
    conn.rollback.assert_called_once()