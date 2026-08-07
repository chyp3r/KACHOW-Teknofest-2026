"""Unit tests for `Settings.mevzuat_mcp_args`.

`MEVZUAT_MCP_ARGS` is a plain `str` field, not `list[str]`, and that type choice
is itself the fix under test: pydantic-settings JSON-decodes any env var bound to
a structured type *before* the model's own validators run, so a `list[str]` field
made the obvious shell-style value -- `MEVZUAT_MCP_ARGS="--transport stdio"` -- a
hard crash at `Settings()` construction ("error parsing value for field ... from
source EnvSettingsSource"), with no mention of JSON and no field validator ever
given a chance to fix it up. These tests exercise `Settings()` construction
directly rather than mocking the property, because a mock cannot reproduce a
crash that happens during construction itself.
"""

import os
from unittest.mock import patch

from app.core.config import Settings


def _settings_with_env(**env: str) -> Settings:
    with patch.dict(os.environ, env, clear=False):
        return Settings()


def test_the_documented_shell_style_value_no_longer_crashes_at_boot():
    """The exact reproduction from the bug report: this used to raise
    SettingsError before any application code ran at all."""
    settings = _settings_with_env(MEVZUAT_MCP_ARGS="--transport stdio")
    assert settings.mevzuat_mcp_args == ["--transport", "stdio"]


def test_default_is_an_empty_argv():
    settings = _settings_with_env(MEVZUAT_MCP_ARGS="")
    assert settings.mevzuat_mcp_args == []


def test_a_quoted_value_survives_as_one_argument():
    settings = _settings_with_env(MEVZUAT_MCP_ARGS='--label "two words"')
    assert settings.mevzuat_mcp_args == ["--label", "two words"]


def test_multiple_flags_split_correctly():
    settings = _settings_with_env(MEVZUAT_MCP_ARGS="--transport stdio --verbose")
    assert settings.mevzuat_mcp_args == ["--transport", "stdio", "--verbose"]
