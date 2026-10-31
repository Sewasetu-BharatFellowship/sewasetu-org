
from unittest.mock import MagicMock

import app.app as app_module


def test_widow_can_submit_without_husband_employer(
    client, tmp_path, monkeypatch
):
    mobile = "8888888888"
    document = tmp_path / f"{mobile}.pdf"
    document.write_bytes(b"%PDF-1.4\nTest")

    with client.session_transaction() as sess:
        sess["verified_mobile"] = mobile
        sess["doc_path"] = str(document)
        sess["form_data"] = {
            "applicant_name": "Test User",
            "village": "Test Village",
            "block": "Test Block",
            "bank_account": "123456789",
            "ifsc": "TEST0001234",
            "dob": "05/06/1960",
            "gender": "Female",
            "marital_status": "Widowed",
            "husband_name": "Late Test Name",
            "husband_employer": "",
        }

    cursor = MagicMock()
    cursor.fetchone.return_value = (0,)

    connection = MagicMock()
    connection.cursor.return_value = cursor

    monkeypatch.setattr(app_module, "get_db", lambda: connection)
    monkeypatch.setattr(
        app_module,
        "SCHEME_DEADLINE",
        app_module.datetime(2099, 12, 31),
    )
    monkeypatch.setattr(
        app_module, "new_application_no", lambda: "TEST001"
    )

    response = client.post("/declaration")

    assert response.status_code in (200, 302)

    insert_call = next(
        call for call in cursor.execute.call_args_list
        if "INSERT INTO applications" in call.args[0]
    )

    assert insert_call.args[1][6] == "Late Test Name"
    assert insert_call.args[1][7] == ""
