"""Error envelope and exception handlers (plan §9.1). No stack traces are returned to clients."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.rag.filters import InvalidFilterError
from src.services.guardrails import GuardrailError
from src.services.ml.predictor import InvalidKPIError

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


class NotReadyError(ApiError):
    def __init__(self, missing: list[str]):
        super().__init__(503, "NOT_READY", "The backend has no data yet. Run: python -m scripts.bootstrap --source full",
                         {"missing": missing})


class NotFoundError(ApiError):
    def __init__(self, what: str):
        super().__init__(404, "NOT_FOUND", f"{what} not found")


def envelope(request: Request, status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    rid = getattr(request.state, "request_id", "")
    return JSONResponse(status_code=status, headers={"X-Request-ID": rid},
                        content={"error": {"code": code, "message": message, "details": details or {},
                                           "request_id": rid}})


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(request: Request, exc: ApiError):
        return envelope(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
        return envelope(request, 422, "INVALID_INPUT", "Check the highlighted values.", {"errors": errors})

    @app.exception_handler(InvalidFilterError)
    async def _filter(request: Request, exc: InvalidFilterError):
        return envelope(request, 400, "INVALID_FILTER", str(exc), exc.details)

    @app.exception_handler(GuardrailError)
    async def _guardrail(request: Request, exc: GuardrailError):
        return envelope(request, 400, exc.code, exc.message, exc.details)

    @app.exception_handler(InvalidKPIError)
    async def _kpi(request: Request, exc: InvalidKPIError):
        return envelope(request, 422, "INVALID_INPUT", str(exc))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        log.exception("unhandled error (request %s)", getattr(request.state, "request_id", ""))
        return envelope(request, 500, "INTERNAL_ERROR", "Unexpected server error. Quote the request_id when reporting it.")
