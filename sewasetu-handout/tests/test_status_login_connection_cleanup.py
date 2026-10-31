import pytest
from unittest.mock import MagicMock, call


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


def test_status_login_closes_first_connection_on_query_failure(
    app_module, monkeypatch
):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.execute.side_effect = RuntimeError("Password query failed")

    monkeypatch.setattr(app_module, "get_db", lambda: conn)

    with app_module.app.test_client() as client:
        with pytest.raises(RuntimeError, match="Password query failed"):
            client.post(
                "/status",
                data={"mobile": "9876543210", "password": "test-password"},
            )

    cur.close.assert_called_once()
    conn.close.assert_called_once()
    conn.rollback.assert_called_once()


def test_status_login_closes_second_connection_on_query_failure(
    app_module, monkeypatch
):
    first_conn = MagicMock()
    first_cur = MagicMock()
    first_conn.cursor.return_value = first_cur

    second_conn = MagicMock()
    second_cur = MagicMock()
    second_conn.cursor.return_value = second_cur
    second_cur.execute.side_effect = RuntimeError("Application query failed")

    connections = iter([first_conn, second_conn])
    monkeypatch.setattr(app_module, "get_db", lambda: next(connections))

    monkeypatch.setattr(
        app_module,
        "hash_password",
        lambda password: "hashed-password",
    )

    first_cur.fetchone.return_value = ("hashed-password",)

    with app_module.app.test_client() as client:
        with pytest.raises(RuntimeError, match="Application query failed"):
            client.post(
                "/status",
                data={"mobile": "9876543210", "password": "test-password"},
            )

    first_cur.close.assert_called_once()
    first_conn.close.assert_called_once()

    second_cur.close.assert_called_once()
    second_conn.close.assert_called_once()
    second_conn.rollback.assert_called_once()