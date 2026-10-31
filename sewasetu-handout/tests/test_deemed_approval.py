
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "scripts"
    / "deemed_approval.py"
)


@pytest.fixture
def job(monkeypatch):
    """Load the job with mocked database and SMS dependencies."""

    import psycopg2
    import requests

    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value = cursor

    monkeypatch.setenv("DB_PASSWORD", "test-password")
    monkeypatch.setattr(psycopg2, "connect", MagicMock(return_value=connection))
    monkeypatch.setattr(requests, "post", MagicMock())

    spec = importlib.util.spec_from_file_location(
        "deemed_approval_test", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module, connection, cursor, requests


def test_job_approves_overdue_pending_applications(job):
    module, connection, cursor, requests = job

    application = ("APP-001", "9876543210")
    cursor.fetchall.return_value = [application]

    module.main()

    query = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]

    assert "DEEMED_APPROVED" in query
    assert "RTPS-AUTO" in query
    assert "PENDING" in query

    now, cutoff = params

    assert isinstance(now, datetime)
    assert isinstance(cutoff, datetime)

    assert abs(
        (now - cutoff) - timedelta(days=module.SLA_DAYS)
    ) < timedelta(seconds=1)

    requests.post.assert_called_once()
    assert requests.post.call_args.kwargs["json"]["to"] == "9876543210"

    connection.commit.assert_called_once()
    cursor.close.assert_called_once()
    connection.close.assert_called_once()


def test_job_handles_sms_failure(job):
    module, connection, cursor, requests = job

    cursor.fetchall.return_value = [("APP-002", "9876543211")]
    requests.post.side_effect = Exception("SMS gateway unavailable")

    # SMS failure should not crash the approval job.
    module.main()

    connection.commit.assert_called_once()
    connection.close.assert_called_once()


def test_job_uses_configured_sla_boundary(job):

    module, connection, cursor, requests = job

    cursor.fetchall.return_value = []

    before = datetime.now()
    module.main()
    after = datetime.now()

    now, cutoff = cursor.execute.call_args.args[1]

    expected_sla = timedelta(days=module.SLA_DAYS)

    assert before <= now <= after
    assert before - expected_sla <= cutoff <= after - expected_sla

    connection.commit.assert_called_once()
    requests.post.assert_not_called()

def test_job_uses_config_path_from_environment():
    
    import os
    import subprocess
    import sys

    test_config = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "config"
        / "test.ini"
    )

    env = os.environ.copy()
    env["DEEMED_APPROVAL_CONFIG"] = str(test_config)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import runpy; "
                "m = runpy.run_path("
                + repr(str(SCRIPT_PATH))
                + "); "
                "assert m['config'].get('database', 'name') "
                "== 'sewasetu_test'"
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

def test_job_closes_database_resources_when_query_fails(job):
    module, connection, cursor, requests = job

    cursor.execute.side_effect = Exception("Database query failed")

    with pytest.raises(Exception, match="Database query failed"):
        module.main()

    cursor.close.assert_called_once()
    connection.close.assert_called_once()
    connection.rollback.assert_called_once()


def test_job_logs_failed_sms_notifications(job, caplog):
    module, connection, cursor, requests = job

    cursor.fetchall.return_value = [
        ("APP-003", "9876543212")
    ]
    requests.post.side_effect = Exception("Gateway unavailable")

    with caplog.at_level("ERROR"):
        module.main()

    assert "APP-003" in caplog.text
    assert "SMS notification failed" in caplog.text

    connection.commit.assert_called_once()
    connection.close.assert_called_once()