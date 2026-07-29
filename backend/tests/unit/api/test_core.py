import pytest
from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from app.api.exceptions import (
    AIException,
    BaseAppException,
    NotFoundException,
    app_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.api.middleware import (
    ResponseTimeMiddleware,
    StructuredLoggingMiddleware,
)
from app.api.responses import SuccessResponse

# Define a test model for validation testing
class DummyPayload(BaseModel):
    name: str = Field(min_length=3)
    age: int


# Create a test FastAPI app specifically to isolate and test API Core components
test_app = FastAPI()
test_app.add_middleware(StructuredLoggingMiddleware)
test_app.add_middleware(ResponseTimeMiddleware)

test_app.add_exception_handler(BaseAppException, app_exception_handler)
test_app.add_exception_handler(RequestValidationError, validation_exception_handler)
test_app.add_exception_handler(HTTPException, http_exception_handler)
test_app.add_exception_handler(Exception, generic_exception_handler)

router = APIRouter()


@router.get("/test-success")
async def get_success():
    return SuccessResponse(data={"message": "Yay success!"}, meta={"custom_key": "val"})


@router.get("/test-custom-exception")
async def get_custom_exception():
    raise NotFoundException(message="Belge bulunamadı.")


@router.get("/test-ai-exception")
async def get_ai_exception():
    raise AIException(message="Ollama cevap vermedi.", details={"model": "qwen"})


@router.get("/test-http-exception")
async def get_http_exception():
    raise HTTPException(status_code=400, detail="Standard HTTP exception.")


@router.post("/test-validation")
async def post_validation(payload: DummyPayload):
    return SuccessResponse(data=payload.model_dump())


@router.get("/test-generic-exception")
async def get_generic_exception():
    raise ValueError("Unexpected python error.")


test_app.include_router(router)
client = TestClient(test_app, raise_server_exceptions=False)


def test_success_response():
    response = client.get("/test-success")
    assert response.status_code == 200

    json_data = response.json()
    assert json_data["success"] is True
    assert json_data["data"] == {"message": "Yay success!"}
    assert json_data["error"] is None
    assert "timestamp" in json_data["meta"]
    assert json_data["meta"]["custom_key"] == "val"

    # Verify X-Response-Time-Ms header is present
    assert "X-Response-Time-Ms" in response.headers


def test_custom_exception_handling():
    response = client.get("/test-custom-exception")
    assert response.status_code == 404

    json_data = response.json()
    assert json_data["success"] is False
    assert json_data["data"] is None
    assert json_data["error"]["code"] == "NOT_FOUND"
    assert json_data["error"]["message"] == "Belge bulunamadı."


def test_ai_exception_handling():
    response = client.get("/test-ai-exception")
    assert response.status_code == 502

    json_data = response.json()
    assert json_data["success"] is False
    assert json_data["error"]["code"] == "AI_EXECUTION_ERROR"
    assert json_data["error"]["message"] == "Ollama cevap vermedi."
    assert json_data["error"]["details"] == {"model": "qwen"}


def test_http_exception_handling():
    response = client.get("/test-http-exception")
    assert response.status_code == 400

    json_data = response.json()
    assert json_data["success"] is False
    assert json_data["error"]["code"] == "HTTP_ERROR"
    assert json_data["error"]["message"] == "Standard HTTP exception."


def test_validation_exception_handling():
    # Pass invalid payload to trigger RequestValidationError
    response = client.post(
        "/test-validation", json={"name": "ab", "age": "not-a-number"}
    )
    assert response.status_code == 422

    json_data = response.json()
    assert json_data["success"] is False
    assert json_data["error"]["code"] == "VALIDATION_ERROR"
    assert (
        json_data["error"]["message"]
        == "Girdi verilerinin doğrulanması başarısız oldu."
    )
    assert "validation_errors" in json_data["error"]["details"]

    # Should contain structured validation error details
    val_errors = json_data["error"]["details"]["validation_errors"]
    assert len(val_errors) == 2  # age field and name field (min_length)


def test_generic_exception_handling():
    response = client.get("/test-generic-exception")
    assert response.status_code == 500

    json_data = response.json()
    assert json_data["success"] is False
    assert json_data["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert (
        json_data["error"]["message"]
        == "Sunucuda beklenmeyen dahili bir hata oluştu."
    )
    assert json_data["error"]["details"]["error_type"] == "ValueError"

