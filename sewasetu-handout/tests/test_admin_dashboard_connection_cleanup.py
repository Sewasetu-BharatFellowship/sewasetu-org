
from unittest.mock import MagicMock

import pytest


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


def test_admin_dashboard_closes_db_resources_when_query_fails(
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
            session["admin"] = True

        with pytest.raises(RuntimeError, match="Database query failed"):
            client.get("/admin/dashboard")

    cur.close.assert_called_once()
    conn.close.assert_called_once()
