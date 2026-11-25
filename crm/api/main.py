"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from ..config import Settings
from ..db import make_engine, make_session_factory
from ..errors import (
    ContractLocked,
    ContractNoDuplicate,
    ContractNotFound,
    InvalidESignEvent,
    InvalidESignTransition,
    PermissionDenied,
    ReasonRequired,
    ServiceCallerRequired,
    TerminateNotAllowed,
)
from ..validation.contract import ContractValidationError
from .routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    app = FastAPI(
        title="Member Space Platform - CRM contracts",
        version="1.0.0",
        description=(
            "Contract field validation, post-signature locking and the "
            "idempotent e-signature status callback flow."
        ),
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.include_router(router)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    _register_error_handlers(app)
    return app


def _error(status_code: int, code: str, detail: str | None = None, **extra: object) -> JSONResponse:
    content: dict[str, object] = {"error": code}
    if detail:
        content["detail"] = detail
    content.update(extra)
    return JSONResponse(status_code=status_code, content=content)


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ContractNotFound)
    async def _not_found(request: Request, exc: ContractNotFound) -> JSONResponse:
        return _error(404, "CRM_CONTRACT_NOT_FOUND", str(exc))

    @app.exception_handler(ContractNoDuplicate)
    async def _duplicate(request: Request, exc: ContractNoDuplicate) -> JSONResponse:
        return _error(409, "CRM_CONTRACT_NO_DUPLICATE", str(exc))

    @app.exception_handler(ContractLocked)
    async def _locked(request: Request, exc: ContractLocked) -> JSONResponse:
        return _error(409, "CRM_CONTRACT_LOCKED", str(exc), fields=list(exc.fields))

    @app.exception_handler(InvalidESignTransition)
    async def _invalid_transition(
        request: Request, exc: InvalidESignTransition
    ) -> JSONResponse:
        return _error(409, "CRM_CONTRACT_INVALID_ESIGN_TRANSITION", str(exc))

    @app.exception_handler(InvalidESignEvent)
    async def _invalid_event(request: Request, exc: InvalidESignEvent) -> JSONResponse:
        return _error(422, "CRM_CONTRACT_ESIGN_EVENT_INVALID", str(exc))

    @app.exception_handler(TerminateNotAllowed)
    async def _terminate_not_allowed(
        request: Request, exc: TerminateNotAllowed
    ) -> JSONResponse:
        return _error(409, "CRM_CONTRACT_TERMINATE_INVALID_STATE", str(exc))

    @app.exception_handler(ReasonRequired)
    async def _reason_required(request: Request, exc: ReasonRequired) -> JSONResponse:
        return _error(422, "CRM_CONTRACT_REASON_REQUIRED", str(exc))

    @app.exception_handler(ContractValidationError)
    async def _validation_error(
        request: Request, exc: ContractValidationError
    ) -> JSONResponse:
        return _error(
            422,
            "CRM_CONTRACT_VALIDATION_FAILED",
            f"{len(exc.issues)} contract field(s) failed validation",
            issues=[
                {"field": issue.field, "code": issue.code, "message": issue.message}
                for issue in exc.issues
            ],
        )

    @app.exception_handler(PermissionDenied)
    async def _permission_denied(
        request: Request, exc: PermissionDenied
    ) -> JSONResponse:
        return _error(403, "PERMISSION_DENIED", str(exc))

    @app.exception_handler(ServiceCallerRequired)
    async def _service_only(
        request: Request, exc: ServiceCallerRequired
    ) -> JSONResponse:
        return _error(403, "SERVICE_CALLER_REQUIRED", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error(
            422,
            "REQUEST_VALIDATION_FAILED",
            "request body or parameters failed schema validation",
            issues=[
                {
                    "field": ".".join(str(part) for part in error.get("loc", ())),
                    "code": error.get("type", "invalid"),
                    "message": str(error.get("msg", "")),
                }
                for error in exc.errors()
            ],
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        return _error(409, "CONSTRAINT_VIOLATION", "the change violates a database constraint")

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError) -> JSONResponse:
        return _error(422, "INVALID_REQUEST", str(exc))


app = create_app()
