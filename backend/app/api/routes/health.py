"""Health endpoints.

/health is a liveness check (is the process answering?) and deliberately does
not touch the database. /health/ready is a readiness check that confirms the
database is reachable, so the two failure modes can be told apart.
"""

import logging

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", summary="Liveness check")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/ready",
    summary="Readiness check (database connectivity)",
    responses={503: {"description": "Database unavailable"}},
)
def readiness(db: DbSession) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # The driver's error message may contain the host or user name, so it is
        # not logged, and the client receives no internal details.
        logger.error("Readiness check failed: database unavailable")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "database": "unreachable"},
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})
