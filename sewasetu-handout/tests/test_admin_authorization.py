import pytest

import app.app as app_module

def login_as_citizen(client, mobile="8888888888"):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["portal_mobile"] = mobile

        
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
