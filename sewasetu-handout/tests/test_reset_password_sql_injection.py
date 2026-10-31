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


def test_reset_password_uses_parameterized_queries(app_module, monkeypatch):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    cur.fetchone.side_effect = [
        ("9876543210",),
        None,
    ]

    monkeypatch.setattr(app_module, "get_db", lambda: conn)

    with app_module.app.test_client() as client:
        client.post(
            "/status/reset",
            data={"mobile": "9876543210' OR '1'='1"},
        )

    executed_queries = cur.execute.call_args_list

    assert len(executed_queries) >= 1

    for query_call in executed_queries:
        assert len(query_call.args) == 2

        query, params = query_call.args

        assert "%s" in query
        assert params is not None
        assert "9876543210' OR '1'='1" not in query