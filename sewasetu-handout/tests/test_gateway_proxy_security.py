def test_public_gateway_proxy_is_not_exposed(client):
    paths = [
        "/__gateway/",
        "/__gateway/api/messages",
        "/__gateway/api/send",
    ]

    for path in paths:
        response = client.get(path)
        assert response.status_code == 404