"""Faz 5: production must not boot with REQUIRE_AUTH left off."""

import pytest

from app.lifespan import _require_auth_in_production
from app.core.config import settings


@pytest.fixture(autouse=True)
def _restore_settings():
    original_environment = settings.ENVIRONMENT
    original_require_auth = settings.REQUIRE_AUTH
    yield
    settings.ENVIRONMENT = original_environment
    settings.REQUIRE_AUTH = original_require_auth


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
