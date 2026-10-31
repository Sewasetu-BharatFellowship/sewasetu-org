import pytest
import app.app as app_module


@pytest.mark.parametrize("captcha", ["", "999", "wrong"])
def test_apply_rejects_invalid_captcha(client, monkeypatch, captcha):
    client.get("/apply")

    def fail_if_db_accessed():
        pytest.fail("Invalid CAPTCHA must not access the database")

    monkeypatch.setattr(app_module, "get_db", fail_if_db_accessed)

    response = client.post("/apply", data={
        "mobile": "8888888888",
        "captcha": captcha,
    })

    assert response.status_code == 200


def test_apply_accepts_correct_captcha(client, monkeypatch):
    client.get("/apply")

    with client.session_transaction() as sess:
        answer = str(sess["captcha_answer"])

    class FakeCursor:
        def execute(self, *args):
            pass

        def close(self):
            pass

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(
        app_module, "get_db", lambda: FakeConnection()
    )
    monkeypatch.setattr(app_module, "send_sms", lambda *args: None)

    response = client.post("/apply", data={
        "mobile": "8888888888",
        "captcha": answer,
    })

    assert response.status_code == 302
    assert response.location.endswith("/verify")