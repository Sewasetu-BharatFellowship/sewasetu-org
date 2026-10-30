
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app" / "scripts" / "deemed_approval.py"
CONFIG = ROOT / "app" / "config" / "test.ini"

NETWORK = "sewasetu-handout_default"
DB_PASSWORD = "sewasetu123"


def test_real_postgres_deemed_approval():
    assert CONFIG.exists(), "test.ini is missing"

    runner = (
        'import runpy, requests; '
        'from unittest.mock import Mock; '
        'requests.post = Mock(); '
        'runpy.run_path("/job/deemed_approval.py", run_name="__main__"); '
        'assert requests.post.call_count == 1; '
        'assert requests.post.call_args.kwargs["json"]["to"] == "9876543210"'
    )

    command = [
        "docker", "run", "--rm",
        "--network", NETWORK,
        "-e", "DEEMED_APPROVAL_CONFIG=/test.ini",
        "-v", f"{SCRIPT}:/job/deemed_approval.py:ro",
        "-v", f"{CONFIG}:/test.ini:ro",
        "python:3.11-slim",
        "sh", "-c",
        "pip install -q psycopg2-binary requests && python -c "
        + shlex.quote(runner),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout

    query = """
    SELECT application_no, status, decided_by
    FROM applications
    WHERE application_no IN ('TEST-001', 'TEST-002', 'TEST-003')
    ORDER BY application_no;
    """

    verify = subprocess.run(
        [
            "docker", "run", "--rm",
            "--network", NETWORK,
            "-e", "PGPASSWORD=" + DB_PASSWORD,
            "postgres:15",
            "psql", "-h", "db",
            "-U", "sewasetu",
            "-d", "sewasetu_test",
            "-A", "-F", "|",
            "-c", query,
        ],
        capture_output=True,
        text=True,
    )

    assert verify.returncode == 0, verify.stderr

    assert "TEST-001|DEEMED_APPROVED|RTPS-AUTO" in verify.stdout
    assert "TEST-002|PENDING|" in verify.stdout
    assert "TEST-003|APPROVED|" in verify.stdout
