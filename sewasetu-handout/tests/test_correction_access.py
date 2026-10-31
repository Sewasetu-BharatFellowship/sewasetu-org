
import pytest

from app import app as app_module


class MockCursor:
    def __init__(self, row):
        self.row = row
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True


class MockConnection:
    def __init__(self, row):
        self.cur = MockCursor(row)
        self.closed = False

    def cursor(self):
        return self.cur

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def login_as_citizen(client, mobile="8888888888"):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["portal_mobile"] = mobile


def test_edit_application_requires_login(client):
    response = client.get("/application/1/edit")

    assert response.status_code == 302
    assert "/status" in response.location


def test_citizen_cannot_edit_another_application(client, monkeypatch):
    login_as_citizen(client, "8888888888")

    connection = MockConnection(None)

    monkeypatch.setattr(
        app_module, "get_db", lambda: connection
    )

    response = client.get("/application/1/edit")

    assert response.status_code == 404

    query, params = connection.cur.executed[0]
    assert "mobile = %s" in query
    assert params == (1, "8888888888")


def test_citizen_cannot_edit_application_not_awaiting_correction(
    client, monkeypatch
):
    login_as_citizen(client)

    row = (
        "Test User",
        "8888888888",
        None,
        "Male",
        "Married",
        "",
        "",
        "Test Village",
        "Test Block",
        "123456789",
        "TEST0001234",
        "document.pdf",
        "PENDING",
    )

    connection = MockConnection(row)

    monkeypatch.setattr(
        app_module, "get_db", lambda: connection
    )

    response = client.get("/application/1/edit")

    assert response.status_code == 302
    assert "/application/1" in response.location


def test_correction_session_requires_correction_status(client, monkeypatch):
    login_as_citizen(client)

    with client.session_transaction() as sess:
        sess["verified_mobile"] = "8888888888"
        sess["correction_application_id"] = 1

    connection = MockConnection(("PENDING",))

    monkeypatch.setattr(
        app_module, "get_db", lambda: connection
    )

    response = client.get("/form/1")

    assert response.status_code == 302
    assert "/status" in response.location



@pytest.mark.parametrize("route", ["/upload", "/declaration"])
def test_upload_and_declaration_reject_invalid_correction_session(
    client, monkeypatch, route
):
    login_as_citizen(client)

    with client.session_transaction() as sess:
        sess["verified_mobile"] = "8888888888"
        sess["correction_application_id"] = 1

    connection = MockConnection(("PENDING",))
    monkeypatch.setattr(
        app_module, "get_db", lambda: connection
    )

    response = client.get(route)

    assert response.status_code == 302
    assert "/status" in response.location

