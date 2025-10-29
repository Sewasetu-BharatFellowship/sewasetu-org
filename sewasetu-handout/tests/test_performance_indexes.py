from pathlib import Path
import re


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "app" / "schema.sql"


def normalize_sql(sql):
    return re.sub(r"\s+", " ", sql.lower()).strip()


def test_applications_mobile_index_exists():
    schema = normalize_sql(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert re.search(
        r"create index(?: if not exists)?\s+\w+\s+"
        r"on applications\s*\(\s*mobile\s*\)",
        schema,
    ), "Missing index on applications.mobile"


def test_applications_status_submitted_index_exists():
    schema = normalize_sql(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert re.search(
        r"create index(?: if not exists)?\s+\w+\s+"
        r"on applications\s*\(\s*status\s*,\s*submitted_at\s*\)",
        schema,
    ), "Missing composite index on applications(status, submitted_at)"


def test_portal_users_mobile_is_already_primary_key():
    schema = normalize_sql(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert re.search(
        r"mobile\s+varchar\s*\(\s*15\s*\)\s+primary key",
        schema,
    ), "portal_users.mobile should remain a primary key"