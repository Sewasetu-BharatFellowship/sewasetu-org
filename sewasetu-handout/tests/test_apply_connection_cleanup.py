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


def test_apply_closes_db_resources_when_query_fails(app_module, monkeypatch):
    conn = MagicMock()
    cur = MagicMock()

    conn.cursor.return_value = cur
    cur.execute.side_effect = RuntimeError("Database query failed")

    monkeypatch.setattr(app_module, "get_db", lambda: conn)
    monkeypatch.setattr(app_module, "deadline_remaining", lambda: 100)

    with app_module.app.test_client() as client:
        # Set the expected CAPTCHA answer in the session.
        with client.session_transaction() as sess:
            sess["captcha_answer"] = 7

        # Submit a valid CAPTCHA so the request reaches the database query.
        with pytest.raises(RuntimeError, match="Database query failed"):
            client.post(
                "/apply",
                data={
                    "mobile": "9876543210",
                    "captcha": "7",
                },
            )

    # Verify database resources are properly cleaned up.
    cur.close.assert_called_once()
    conn.close.assert_called_once()
    conn.rollback.assert_called_once()