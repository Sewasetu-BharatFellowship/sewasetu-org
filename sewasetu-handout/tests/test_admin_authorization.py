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


@pytest.mark.parametrize(
    "endpoint",
    [
        "/admin/dashboard",
        "/admin/applications",
        "/admin/application/1",
    ],
)
def test_citizen_cannot_access_admin_pages(client, monkeypatch, endpoint):
    login_as_citizen(client, "8888888888")

    def fail_if_db_accessed():
        pytest.fail("Unauthorized citizen request accessed database")

    monkeypatch.setattr(app_module, "get_db", fail_if_db_accessed)

    response = client.get(endpoint)

    assert response.status_code in (302, 403)



def test_admin_login_sets_admin_session(client):
    response = client.post(
        "/admin",
        data={
            "username": "test-admin",
            "password": "test-password",
        },
    )

    assert response.status_code == 302
    assert "/admin/dashboard" in response.location

    with client.session_transaction() as sess:
        assert sess.get("logged_in") is True
        assert sess.get("admin") is True