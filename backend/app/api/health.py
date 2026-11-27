import logging
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import error_response
from app.infrastructure.database import check_database

router = APIRouter(prefix="/api/v1", tags=["health"])
logger = logging.getLogger("app.health")


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse, responses={503: {"description": "Not ready"}})
def readiness(request: Request) -> HealthResponse | JSONResponse:
    try:
        check_database(request.app.state.engine)
    except SQLAlchemyError:
        logger.exception("Database readiness check failed")
        return error_response(503, "not_ready", "Database is unavailable.")
    return HealthResponse(status="ready")
