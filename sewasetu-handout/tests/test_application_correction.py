
import pytest

from app import app as app_module


class MockCursor:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount
        self.executed = []
        self.closed = False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def close(self):
        self.closed = True


class MockConnection:
    def __init__(self, rowcount=1):
        self.cur = MockCursor(rowcount)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def login_as_admin(client):
    with client.session_transaction() as sess:
        sess["admin"] = True


def login_as_citizen(client):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["portal_mobile"] = "8888888888"


def test_citizen_cannot_request_application_correction(client, monkeypatch):
    login_as_citizen(client)

    def fail_if_db_accessed():
        pytest.fail("Unauthorized citizen accessed the database")

    monkeypatch.setattr(app_module, "get_db", fail_if_db_accessed)

    response = client.post(
        "/admin/request-correction/1",
        data={"correction_reason": "Incorrect bank details"},
    )

    assert response.status_code == 403


def test_admin_correction_requires_reason(client, monkeypatch):
    login_as_admin(client)

    def fail_if_db_accessed():
        pytest.fail("Database should not be accessed without a reason")

    monkeypatch.setattr(app_module, "get_db", fail_if_db_accessed)

    response = client.post(
        "/admin/request-correction/1",
        data={"correction_reason": "   "},
    )

    assert response.status_code == 302
    assert "/admin/application/1" in response.location


def test_admin_can_request_correction(client, monkeypatch):
    login_as_admin(client)

    connection = MockConnection(rowcount=1)
    monkeypatch.setattr(
        app_module, "get_db", lambda: connection
    )

    response = client.post(
        "/admin/request-correction/1",
        data={"correction_reason": "Please correct the bank account number."},
    )

    assert response.status_code == 302
    assert connection.committed is True
    assert connection.cur.closed is True
    assert connection.closed is True

    query, params = connection.cur.executed[0]

    assert "CORRECTION_REQUIRED" in query
    assert params[0] == "Please correct the bank account number."
    assert params[2] == 1


def test_admin_correction_rejects_non_pending_application(client, monkeypatch):
    login_as_admin(client)

    connection = MockConnection(rowcount=0)
    monkeypatch.setattr(
        app_module, "get_db", lambda: connection
    )

    response = client.post(
        "/admin/request-correction/1",
        data={"correction_reason": "Please correct the IFSC."},
    )

    assert response.status_code == 302
    assert connection.rolled_back is True
    assert connection.committed is False
    assert connection.cur.closed is True
    assert connection.closed is True



def test_correction_update_preserves_application_identity():
    import inspect

    source = inspect.getsource(app_module.handle_submission)

    assert "UPDATE applications" in source
    assert "INSERT INTO applications" in source
    assert "WHERE id = %s" in source
    assert "AND mobile = %s" in source
    assert "AND status = 'CORRECTION_REQUIRED'" in source
    assert "RETURNING id, application_no" in source
    assert "status = 'PENDING'" in source
    assert "correction_reason = NULL" in source
    assert "correction_requested_at = NULL" in source



def test_correction_resubmission_updates_existing_application(
    client, monkeypatch, tmp_path
):
    from datetime import datetime
    import os

    connection = MockConnection(rowcount=1)
    connection.cur.fetchone = lambda: (1, "SEWA-2026-0001")

    document = tmp_path / "corrected_document.pdf"
    document.write_bytes(b"%PDF-1.4 test document")

    sms_calls = []

    monkeypatch.setattr(app_module, "get_db", lambda: connection)
    monkeypatch.setattr(
        app_module, "correction_session_is_valid", lambda: True
    )
    monkeypatch.setattr(
        app_module, "generate_acknowledgment",
        lambda cur, app_id: b"mock acknowledgment PDF"
    )
    monkeypatch.setattr(
        app_module, "send_sms",
        lambda mobile, message: sms_calls.append((mobile, message))
    )
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "SCHEME_DEADLINE", datetime.max)

    with client.session_transaction() as sess:
        sess["verified_mobile"] = "8888888888"
        sess["correction_application_id"] = 1
        sess["doc_path"] = str(document)
        sess["form_data"] = {
            "applicant_name": "Test Applicant",
            "dob": "01/01/1960",
            "gender": "Male",
            "marital_status": "Married",
            "husband_name": "",
            "husband_employer": "",
            "village": "Test Village",
            "block": "Test Block",
            "bank_account": "1234567890",
            "ifsc": "TEST0001234",
        }

    response = client.post("/declaration", follow_redirects=False)

    assert response.status_code == 200
    assert connection.committed is True
    assert connection.closed is True
    assert connection.cur.closed is True

    queries = [query for query, params in connection.cur.executed]

    assert any(
        "UPDATE applications" in query
        and "CORRECTION_REQUIRED" in query
        and "RETURNING id, application_no" in query
        for query in queries
    )

    assert not any(
        "INSERT INTO applications" in query
        for query in queries
    )

    assert os.path.isfile(tmp_path / "ack" / "1.pdf")

    with client.session_transaction() as sess:
        assert "correction_application_id" not in sess
        assert "verified_mobile" not in sess
        assert "form_data" not in sess
        assert "doc_path" not in sess

    assert len(sms_calls) == 1
    assert sms_calls[0][0] == "8888888888"
    assert "resubmitted successfully" in sms_calls[0][1]
