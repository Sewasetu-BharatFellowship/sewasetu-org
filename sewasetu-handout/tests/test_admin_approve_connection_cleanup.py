
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


def test_admin_approve_closes_db_resources_when_query_fails(
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
            client.post("/admin/approve/1")

    cur.close.assert_called_once()
    conn.close.assert_called_once()

def test_admin_approve_succeeds(app_module, monkeypatch):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    monkeypatch.setattr(app_module, "get_db", lambda: conn)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["logged_in"] = True
            session["admin"] = True

        response = client.post("/admin/approve/1")

    assert response.status_code == 302
    assert "admin" in response.location

    query = cur.execute.call_args.args[0]
    assert "APPROVED" in query

    conn.commit.assert_called_once()
    cur.close.assert_called_once()
    conn.close.assert_called_once()
    
def test_admin_approve_rejects_non_pending_application(app_module, monkeypatch):
    conn = MagicMock()
    cur = MagicMock()
    cur.rowcount = 0
    conn.cursor.return_value = cur

    monkeypatch.setattr(app_module, "get_db", lambda: conn)

    with app_module.app.test_client() as client:
        with client.session_transaction() as session:
            session["logged_in"] = True
            session["admin"] = True

        response = client.post("/admin/approve/1")

    query = cur.execute.call_args.args[0]

    assert "status = 'PENDING'" in query
    assert response.status_code == 302
    conn.commit.assert_not_called()
    cur.close.assert_called_once()
    conn.close.assert_called_once()