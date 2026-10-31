
import pytest

from app import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client


class MockCursor:
    def __init__(self, row=None):
        self.row = row
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self.row

    def close(self):
        pass


class MockConnection:
    def __init__(self, row=None):
        self.cur = MockCursor(row)

    def cursor(self):
        return self.cur

    def close(self):
        pass


CITIZEN_B_ROW = (
    "SSP260012345",
    "Citizen B",
    "9999999999",
    None,
    "Village B",
    "Block B",
    "123456789012",
    "TEST0001234",
    "PENDING",
    None,
    None,
)


def login_as_citizen(client, mobile="8888888888"):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["portal_mobile"] = mobile


def login_as_admin(client):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["admin"] = True


def test_application_requires_login(client):
    response = client.get("/application/1")

    assert response.status_code == 302
    assert "/status" in response.location


def test_citizen_cannot_view_another_citizens_application(
    client, monkeypatch
):
    login_as_citizen(client, "8888888888")

    connection = MockConnection(CITIZEN_B_ROW)
    monkeypatch.setattr(
        app_module, "get_db", lambda: connection
    )

    response = client.get("/application/1")

    assert response.status_code == 403


def test_citizen_can_view_own_application(client, monkeypatch):
    own_row = list(CITIZEN_B_ROW)
    own_row[2] = "8888888888"

    login_as_citizen(client, "8888888888")

    monkeypatch.setattr(
        app_module,
        "get_db",
        lambda: MockConnection(tuple(own_row)),
    )

    response = client.get("/application/1")

    assert response.status_code == 200


def test_admin_can_view_any_application(client, monkeypatch):
    login_as_admin(client)

    monkeypatch.setattr(
        app_module,
        "get_db",
        lambda: MockConnection(CITIZEN_B_ROW),
    )

    response = client.get("/application/1")

    assert response.status_code == 200


def test_acknowledgment_pdf_requires_login(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path))

    ack_dir = tmp_path / "ack"
    ack_dir.mkdir()
    (ack_dir / "1.pdf").write_bytes(b"%PDF-test")

    response = client.get("/ack/1.pdf")

    assert response.status_code == 302
    assert "/status" in response.location


def test_citizen_cannot_download_another_citizens_pdf(
    client, tmp_path, monkeypatch
):
    login_as_citizen(client, "8888888888")

    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path))

    ack_dir = tmp_path / "ack"
    ack_dir.mkdir()
    (ack_dir / "1.pdf").write_bytes(b"%PDF-test")

    connection = MockConnection(("9999999999",))
    monkeypatch.setattr(
        app_module, "get_db", lambda: connection
    )

    response = client.get("/ack/1.pdf")

    assert response.status_code == 403


def test_citizen_can_download_own_pdf(
    client, tmp_path, monkeypatch
):
    login_as_citizen(client, "8888888888")

    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path))

    ack_dir = tmp_path / "ack"
    ack_dir.mkdir()
    (ack_dir / "1.pdf").write_bytes(b"%PDF-test")

    connection = MockConnection(("8888888888",))
    monkeypatch.setattr(
        app_module, "get_db", lambda: connection
    )

    response = client.get("/ack/1.pdf")

    assert response.status_code == 200
    assert response.data.startswith(b"%PDF")


def test_admin_can_download_any_citizens_pdf(
    client, tmp_path, monkeypatch
):
    login_as_admin(client)

    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path))

    ack_dir = tmp_path / "ack"
    ack_dir.mkdir()
    (ack_dir / "1.pdf").write_bytes(b"%PDF-test")

    connection = MockConnection(("9999999999",))
    monkeypatch.setattr(
        app_module, "get_db", lambda: connection
    )

    response = client.get("/ack/1.pdf")

    assert response.status_code == 200


from datetime import datetime, timedelta


def test_overdue_pending_application_shows_deemed_approval(

    client, monkeypatch
):
    overdue_row = list(CITIZEN_B_ROW)
    overdue_row[2] = "8888888888"
    overdue_row[8] = "PENDING"
    overdue_row[9] = (
        datetime.now() - timedelta(days=app_module.SLA_DAYS + 1)
    )

    login_as_citizen(client, "8888888888")

    monkeypatch.setattr(
        app_module,
        "get_db",
        lambda: MockConnection(tuple(overdue_row)),
    )

    response = client.get("/application/1")

    assert response.status_code == 200
    assert b"APPROVED (RTPS Deemed Approval)" in response.data

@pytest.mark.parametrize(
    "endpoint",
    [
        "/admin/approve/1",
        "/admin/reject/1",
    ],
)
def test_citizen_cannot_approve_or_reject_application(
    client, monkeypatch, endpoint
):
    login_as_citizen(client, "8888888888")

    def fail_if_db_accessed():
        pytest.fail("Unauthorized citizen request accessed database")

    monkeypatch.setattr(
        app_module,
        "get_db",
        fail_if_db_accessed,
    )

    response = client.post(endpoint)

    assert response.status_code == 403