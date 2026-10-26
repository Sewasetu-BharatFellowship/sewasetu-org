
import pytest

from app.app import sanitize


def test_assamese_name_is_not_truncated():
    """Assamese names must be preserved without UTF-8 byte truncation."""
    name = "প্ৰণৱ কলিতা"

    result = sanitize(name)

    assert result == name


def test_bengali_name_is_not_truncated():
    """Bengali Unicode characters must be preserved."""
    name = "অভিষেক মোহান্তি"

    result = sanitize(name)

    assert result == name


def test_long_name_supports_100_characters():
    """Names up to the database's 100-character limit must be preserved."""
    name = "A" * 100

    result = sanitize(name)

    assert result == name


def test_name_is_trimmed():
    """Leading and trailing whitespace should be removed."""
    assert sanitize("  Abhishek  ") == "Abhishek"


def test_none_returns_empty_string():
    assert sanitize(None) == ""


def test_custom_character_limit():
    """The maxlen argument should count characters, not UTF-8 bytes."""
    name = "প্ৰণৱ কলিতা"

    result = sanitize(name, maxlen=5)

    assert result == name[:5]
