"""AuraCinema API entry point.

Run locally with:  uvicorn app.main:app --reload   (from the backend/ folder)
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import auth, health, movies, ratings, recommendations, users, watchlist
from app.core.config import get_settings
from app.services import recommendation_service

API_V1_PREFIX = "/api/v1"

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Code run once when the server starts (before `yield`) and stops (after).

    The recommendation models are loaded here, so the first user does not wait
    for them and any problem with the model files appears in the log at start-up.
    A loading failure does not stop the API: the other endpoints keep working and
    only the recommendation endpoint answers 503.
    """
    recommendation_service.load_recommenders()
    yield


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return validation errors without echoing the submitted values.

    FastAPI's default 422 body includes each invalid "input", which could
    copy a password back into the response (and into proxy or browser logs).
    Only the location, message and error type are returned here.
    """
    errors = [
        {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": errors}
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Hide internal errors (stack traces, SQL, connection details) from clients.

    The traceback is still logged on the server for debugging.
    """
    logger.exception("Unhandled error while processing %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


def create_app() -> FastAPI:
    """Application factory: validates settings and wires up routers."""
    # Fails fast with a clear message if the environment is misconfigured.
    settings = get_settings()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    app = FastAPI(
        title="AuraCinema API",
        version="0.1.0",
        description="Backend for AuraCinema, a movie discovery and recommendation application.",
        lifespan=lifespan,
    )

    # Only the configured frontend origins may call the API from a browser.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # Tokens travel in the Authorization header, not cookies.
        # PATCH is used by PATCH /users/me (partial profile update).
        allow_methods=["GET", "PUT", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # Health checks are unversioned so infrastructure probes never need to change.
    app.include_router(health.router)
    for module in (auth, users, movies, ratings, watchlist, recommendations):
        app.include_router(module.router, prefix=API_V1_PREFIX)

    logger.info("AuraCinema API initialised (environment=%s)", settings.app_env.value)
    return app


app = create_app()
