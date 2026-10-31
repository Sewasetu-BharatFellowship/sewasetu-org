import os
import app.app as app_module


def test_submission_rejects_missing_document(client, monkeypatch):
    with client.session_transaction() as sess:
        sess["verified_mobile"] = "8888888888"
        sess["form_data"] = {
            "applicant_name": "Test User",
            "village": "Test Village",
            "block": "Test Block",
            "bank_account": "123456789",
            "ifsc": "TEST0001234",
            "dob": "01/01/1950",
            "gender": "Female",
            "marital_status": "Married",
        }

    def fail_if_db_accessed():
        raise AssertionError("Submission must reject missing document before DB access")

    monkeypatch.setattr(app_module, "get_db", fail_if_db_accessed)

    response = client.post("/declaration")

    assert response.status_code == 302
    assert "/upload" in response.location