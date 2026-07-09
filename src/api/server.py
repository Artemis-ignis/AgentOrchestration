"""FastAPI application server."""

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from src import __version__
from src.orchestrator import OrchestrationEngine

from .middleware import AuthMiddleware, RateLimitMiddleware, LoggingMiddleware
from .routes import router


def create_app(config: Optional[Dict] = None) -> FastAPI:
    config = config or {}
    engine = OrchestrationEngine(
        max_workers=config.get("max_workers", 10),
        agent_timeout=config.get("agent_timeout", 300),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine_task = asyncio.create_task(engine.start())
        yield
        engine.stop()
        with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(engine_task, timeout=2)

    app = FastAPI(
        title="Agent Orchestrator API",
        version=__version__,
        description="Enterprise Agent Orchestration Platform API",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )
    app.state.engine = engine

    origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # Browsers reject credentialed requests with a wildcard origin,
        # so only allow credentials when explicit origins are configured.
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(AuthMiddleware, api_key=config.get("api_key"))
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(LoggingMiddleware)

    app.include_router(router, prefix="/api/v2")

    dashboard_html = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")

    @app.get("/", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    async def dashboard():
        return HTMLResponse(dashboard_html)

    @app.get("/health")
    async def health():
        return {
            "status": "healthy",
            "version": __version__,
            "engine_running": engine.is_running,
            "agents": engine.registry.count(),
        }

    return app
