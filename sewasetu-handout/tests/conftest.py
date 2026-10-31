import os

# Set test environment before importing the Flask application.
os.environ["FLASK_SECRET_KEY"] = "test-secret"
os.environ["ADMIN_USERNAME"] = "test-admin"
os.environ["ADMIN_PASSWORD"] = "test-password"

import pytest
from app import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as test_client:
        yield test_client