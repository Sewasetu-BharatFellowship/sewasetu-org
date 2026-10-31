
import app.app as app_module


def setup_otp_session(client, attempts=0):
    with client.session_transaction() as sess:
        sess["apply_mobile"] = "8888888888"
        sess["otp_attempts"] = attempts


class FakeCursor:
    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchone(self):
        return ("123456", app_module.datetime.now())

    def close(self):
        pass


class FakeConnection:
    def cursor(self):
        return FakeCursor()

    def rollback(self):
        pass

    def close(self):
        pass


def test_invalid_otp_increments_attempt_counter(client, monkeypatch):
    setup_otp_session(client)

    monkeypatch.setattr(
        app_module, "get_db", lambda: FakeConnection()
    )

    response = client.post("/verify", data={"otp": "000000"})

    assert response.status_code == 200

    with client.session_transaction() as sess:
        assert sess["otp_attempts"] == 1


def test_fifth_invalid_otp_expires_session(client, monkeypatch):
    setup_otp_session(client, attempts=4)

    monkeypatch.setattr(
        app_module, "get_db", lambda: FakeConnection()
    )

    response = client.post("/verify", data={"otp": "000000"})

    assert response.status_code == 302

    with client.session_transaction() as sess:
        assert "apply_mobile" not in sess
        assert "otp_attempts" not in sess


def test_correct_otp_resets_attempt_counter(client, monkeypatch):
    setup_otp_session(client, attempts=2)

    monkeypatch.setattr(
        app_module, "get_db", lambda: FakeConnection()
    )

    response = client.post("/verify", data={"otp": "123456"})

    assert response.status_code == 302

    with client.session_transaction() as sess:
        assert sess.get("verified_mobile") == "8888888888"
        assert "otp_attempts" not in sess
