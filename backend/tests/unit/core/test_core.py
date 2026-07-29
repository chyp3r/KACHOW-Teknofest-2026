"""Core katmanı birim testleri: Enums, Constants, Permissions, Security."""

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException

from app.api.exceptions import (
    BaseAppException,
    app_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.api.middleware import ResponseTimeMiddleware, StructuredLoggingMiddleware
from app.core.constants import (
    AI_WORKFLOW_TIMEOUT_SECONDS,
    ALLOWED_FILE_TYPES,
    CACHE_TTL_SECONDS,
    CORS_ORIGINS,
    DEFAULT_PAGE_SIZE,
    MAX_FILE_SIZE_BYTES,
    MAX_PAGE_SIZE,
    MAX_RETRY_ATTEMPTS,
)
from app.core.enums import DocumentStatus, UserRole
from app.core.permissions import RoleChecker


# ────────────────────────────────────────────────────────────────────────────────
# Enums
# ────────────────────────────────────────────────────────────────────────────────


class TestUserRole:
    def test_values_are_strings(self):
        assert UserRole.ADMIN == "admin"
        assert UserRole.EDITOR == "editor"
        assert UserRole.VIEWER == "viewer"

    def test_all_roles_present(self):
        roles = {r.value for r in UserRole}
        assert roles == {"admin", "editor", "viewer"}


class TestDocumentStatus:
    def test_values_are_strings(self):
        assert DocumentStatus.PENDING == "pending"
        assert DocumentStatus.PROCESSING == "processing"
        assert DocumentStatus.COMPLETED == "completed"
        assert DocumentStatus.FAILED == "failed"
        assert DocumentStatus.ARCHIVED == "archived"

    def test_all_statuses_present(self):
        statuses = {s.value for s in DocumentStatus}
        assert statuses == {"pending", "processing", "completed", "failed", "archived"}


# ────────────────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────────────────


class TestSystemConstants:
    def test_max_file_size_is_50mb(self):
        assert MAX_FILE_SIZE_BYTES == 50 * 1024 * 1024

    def test_default_page_size_less_than_max(self):
        assert DEFAULT_PAGE_SIZE < MAX_PAGE_SIZE

    def test_allowed_file_types_is_list(self):
        assert isinstance(ALLOWED_FILE_TYPES, list)
        assert len(ALLOWED_FILE_TYPES) > 0

    def test_cors_origins_is_list(self):
        assert isinstance(CORS_ORIGINS, list)

    def test_cache_ttl_is_positive(self):
        assert CACHE_TTL_SECONDS > 0

    def test_ai_timeout_is_positive(self):
        assert AI_WORKFLOW_TIMEOUT_SECONDS > 0

    def test_max_retry_attempts_is_positive(self):
        assert MAX_RETRY_ATTEMPTS > 0


# ────────────────────────────────────────────────────────────────────────────────
# Permissions — RoleChecker
# ────────────────────────────────────────────────────────────────────────────────


def _build_test_app() -> tuple[FastAPI, TestClient]:
    """RoleChecker testleri için yalıtılmış bir FastAPI uygulaması döndürür."""
    from fastapi import APIRouter

    app = FastAPI()
    app.add_middleware(StructuredLoggingMiddleware)
    app.add_middleware(ResponseTimeMiddleware)
    app.add_exception_handler(BaseAppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    require_admin = RoleChecker(allowed_roles=[UserRole.ADMIN])
    require_editor_or_admin = RoleChecker(allowed_roles=[UserRole.ADMIN, UserRole.EDITOR])

    router = APIRouter()

    @router.get("/admin-only")
    def admin_endpoint(request, _: None = None):
        request.state.user_role = "admin"
        return require_admin(request)  # type: ignore

    app.include_router(router)
    return app, TestClient(app, raise_server_exceptions=False)


class TestRoleChecker:
    def test_authorized_role_passes(self):
        """Doğru rolle erişim izin verilmeli."""
        from fastapi import Request
        from starlette.datastructures import Headers

        checker = RoleChecker(allowed_roles=[UserRole.ADMIN])

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope=scope)
        request.state.user_role = UserRole.ADMIN

        # Erişim izinliyse hata fırlatmamalı
        result = checker(request)
        assert result is None

    def test_unauthorized_role_raises(self):
        """Yanlış rolle erişim AuthorizationException fırlatmalı."""
        from fastapi import Request
        from app.api.exceptions import AuthorizationException

        checker = RoleChecker(allowed_roles=[UserRole.ADMIN])

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope=scope)
        request.state.user_role = UserRole.VIEWER

        with pytest.raises(AuthorizationException):
            checker(request)

    def test_missing_role_raises(self):
        """Role bilgisi olmayan istekte AuthorizationException fırlatmalı."""
        from fastapi import Request
        from app.api.exceptions import AuthorizationException

        checker = RoleChecker(allowed_roles=[UserRole.ADMIN])

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope=scope)
        # user_role state'e eklenmedi

        with pytest.raises(AuthorizationException):
            checker(request)
