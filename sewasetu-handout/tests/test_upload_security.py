
import io

import app.app as app_module


def login_for_upload(client, mobile="8888888888"):
    with client.session_transaction() as sess:
        sess["verified_mobile"] = mobile


def test_upload_rejects_fake_pdf(client, tmp_path, monkeypatch):
    login_for_upload(client)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path))

    response = client.post(
        "/upload",
        data={"document": (io.BytesIO(b"this is not a PDF"), "fake.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert not list(tmp_path.iterdir())


def test_upload_rejects_files_over_100kb(client, tmp_path, monkeypatch):
    login_for_upload(client)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path))

    content = b"%PDF-1.4\n" + b"A" * 102400

    response = client.post(
        "/upload",
        data={"document": (io.BytesIO(content), "large.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert not list(tmp_path.iterdir())


def test_upload_ignores_user_supplied_filename(client, tmp_path, monkeypatch):
    login_for_upload(client)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path))

    content = b"%PDF-1.4\n% test PDF content"

    response = client.post(
        "/upload",
        data={
            "document": (
                io.BytesIO(content),
                "../../malicious.pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert (tmp_path / "8888888888.pdf").exists()
    assert list(tmp_path.iterdir()) == [tmp_path / "8888888888.pdf"]


def test_upload_accepts_valid_pdf(client, tmp_path, monkeypatch):
    login_for_upload(client)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(tmp_path))

    content = b"%PDF-1.4\n% test PDF content"

    response = client.post(
        "/upload",
        data={"document": (io.BytesIO(content), "document.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert (tmp_path / "8888888888.pdf").read_bytes() == content

    with client.session_transaction() as sess:
        assert sess["doc_path"] == str(tmp_path / "8888888888.pdf")
