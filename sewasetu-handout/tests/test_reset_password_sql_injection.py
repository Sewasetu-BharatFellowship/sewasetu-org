
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


def test_reset_password_uses_parameterized_queries(app_module, monkeypatch):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    cur.fetchone.return_value = ("9876543210",)

    monkeypatch.setattr(app_module, "get_db", lambda: conn)
    monkeypatch.setattr(app_module, "send_sms", lambda *args: None)

    with app_module.app.test_client() as client:
        response = client.post(
            "/status/reset",
            data={"mobile": "9876543210"},
        )

    assert response.status_code == 302

    executed_queries = cur.execute.call_args_list
    assert len(executed_queries) >= 2

    for query_call in executed_queries:
        assert len(query_call.args) == 2

        query, params = query_call.args

        assert "%s" in query
        assert params is not None

    conn.commit.assert_called_once()
    cur.close.assert_called_once()
    conn.close.assert_called_once()


def test_reset_password_rejects_sql_injection_payload(app_module, monkeypatch):
    get_db_called = False

    def unexpected_db_call():
        nonlocal get_db_called
        get_db_called = True
        raise AssertionError("Database should not be accessed")

    monkeypatch.setattr(app_module, "get_db", unexpected_db_call)

    with app_module.app.test_client() as client:
        response = client.post(
            "/status/reset",
            data={"mobile": "9876543210' OR '1'='1"},
        )

    assert response.status_code == 200
    assert get_db_called is False
