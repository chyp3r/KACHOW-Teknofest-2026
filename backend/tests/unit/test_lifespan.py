"""Faz 5: production must not boot with REQUIRE_AUTH or SECRET_KEY left default."""

import pytest

from app.lifespan import (
    _DEFAULT_SECRET_KEY,
    _require_auth_in_production,
    _require_secret_key_in_production,
)
from app.core.config import settings


@pytest.fixture(autouse=True)
def _restore_settings():
    original_environment = settings.ENVIRONMENT
    original_require_auth = settings.REQUIRE_AUTH
    original_secret_key = settings.SECRET_KEY
    yield
    settings.ENVIRONMENT = original_environment
    settings.REQUIRE_AUTH = original_require_auth
    settings.SECRET_KEY = original_secret_key


def test_refuses_to_boot_in_production_with_auth_disabled():
    settings.ENVIRONMENT = "production"
    settings.REQUIRE_AUTH = False

    with pytest.raises(RuntimeError, match="REQUIRE_AUTH"):
        _require_auth_in_production()


def test_boots_in_production_with_auth_enabled():
    settings.ENVIRONMENT = "production"
    settings.REQUIRE_AUTH = True

    _require_auth_in_production()


def test_boots_in_development_regardless_of_require_auth():
    settings.ENVIRONMENT = "development"
    settings.REQUIRE_AUTH = False

    _require_auth_in_production()


def test_refuses_to_boot_in_production_with_default_secret_key():
    settings.ENVIRONMENT = "production"
    settings.SECRET_KEY = _DEFAULT_SECRET_KEY

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _require_secret_key_in_production()


def test_boots_in_production_with_custom_secret_key():
    settings.ENVIRONMENT = "production"
    settings.SECRET_KEY = "a-unique-production-secret"

    _require_secret_key_in_production()


def test_boots_in_development_regardless_of_secret_key():
    settings.ENVIRONMENT = "development"
    settings.SECRET_KEY = _DEFAULT_SECRET_KEY

    _require_secret_key_in_production()
