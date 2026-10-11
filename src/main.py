"""FastAPI application. Run from the repo root:  uvicorn src.main:app --reload --reload-dir src"""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from src.api import errors
from src.api.routes import agents, cases, evaluation, feedback, health, metadata, predict, search, troubleshoot
from src.services.container import ServiceContainer
from src.utils.config import get_settings
from src.utils.net import use_system_certificates

API_PREFIX = "/api/v1"
log = logging.getLogger("netops.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    use_system_certificates()
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    t0 = time.perf_counter()
    app.state.container = ServiceContainer.build(settings)
    c = app.state.container
    log.info("startup in %.1fs ready=%s missing=%s llm_configured=%s", time.perf_counter() - t0, c.ready, c.missing,
             settings.llm_configured)
    yield


app = FastAPI(
    title="AI-Powered Telecom Network Operations Assistant",
    version=health.APP_VERSION,
    description="Similar-incident retrieval, analysis, risk and prioritization over 100k historical 5G KPI records.",
    lifespan=lifespan,
)
errors.install(app)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    log.info("%s %s %s %.0fms rid=%s", request.method, request.url.path, response.status_code,
             (time.perf_counter() - t0) * 1000, request.state.request_id)
    return response


for router in (health.router, metadata.router, search.router, cases.router, agents.router, troubleshoot.router,
               predict.router, feedback.router, evaluation.router):
    app.include_router(router, prefix=API_PREFIX)
