import app.app as app_module


def test_session_lifetime_is_30_minutes():
    assert app_module.app.config["PERMANENT_SESSION_LIFETIME"] == 1800


def test_sessions_are_configured_as_permanent():
    assert "PERMANENT_SESSION_LIFETIME" in app_module.app.config