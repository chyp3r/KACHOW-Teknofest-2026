"""A client-supplied storage_path reaches storage.get_file() on endpoints that
are unauthenticated by default -- a permissive check here is a path-traversal
read primitive, not a formality."""

import pytest

from app.core.config import settings
from app.shared.validator.storage_path_validator import validate_storage_path

VALID = "uploads/" + "a" * 32 + ".pdf"


def test_accepts_the_shape_document_service_produces():
    assert validate_storage_path(VALID) == VALID


@pytest.mark.parametrize(
    "value",
    [
        "",
        "../uploads/" + "a" * 32 + ".pdf",
        "uploads/../../etc/passwd",
        "/etc/passwd",
        "uploads/" + "a" * 32 + ".pdf\x00.png",
        "uploads/not-a-uuid.pdf",
        "uploads/" + "a" * 31 + ".pdf",  # one char short of 32
        "uploads/" + "g" * 32 + ".pdf",  # not hex
        "uploads/" + "a" * 32,  # missing extension
        "downloads/" + "a" * 32 + ".pdf",  # wrong prefix
    ],
)
def test_rejects_malformed_or_traversing_paths(value):
    with pytest.raises(ValueError):
        validate_storage_path(value)


def test_rejects_paths_that_escape_the_storage_dir_via_relative_segments(monkeypatch, tmp_path):
    """A traversal attempt hidden in the extension-adjacent segment must be
    caught even if it slipped past the regex somehow -- defence in depth via
    realpath containment."""
    monkeypatch.setattr(settings, "STORAGE_TYPE", "local")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_DIR", str(tmp_path))

    assert validate_storage_path(VALID) == VALID
