from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    # No scheduler, scanner, or provider network calls during API import/startup.
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if not settings.production else None,
        redoc_url=None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @application.get("/health/live", tags=["health"])
    async def liveness():
        return {"status": "ok", "service": "api"}

    @application.get("/health/ready", tags=["health"])
    async def readiness():
        # Database readiness is wired when the repository/migration layer lands.
        return {"status": "ready", "database": "not-configured-yet"}

    application.include_router(router, prefix=settings.api_prefix, tags=["markets"])
    return application


app = create_app()
