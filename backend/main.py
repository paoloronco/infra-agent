"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app_logging import configure_application_logging, log_event
from config import settings
from db import init_db

# Routers
from routers.chat import router as chat_router
from routers.models_config import router as models_router
from routers.usage import router as usage_router
from routers.logs import router as logs_router
from routers.auth import router as auth_router
from routers.cron import router as cron_router
from routers.attachments import router as attachments_router
from routers.backup import router as backup_router
from routers.systems import router as systems_router
from routers.ssh import router as ssh_router

logging.basicConfig(level=settings.log_level)
configure_application_logging(settings.log_level)
logger = logging.getLogger(__name__)


def _startup() -> None:
    # Ensure JWT secret file exists before init_db() triggers crypto (e.g. _migrate_plaintext_api_keys)
    from auth import _get_secret_key, get_auth_enabled, init_default_admin
    _get_secret_key()

    init_db()
    logger.info("Database initialized")
    log_event(
        level="INFO",
        category="system",
        event_type="startup",
        message="Backend startup completed",
        source="main",
        details={"version": settings.api_version},
    )

    logger.info("Authentication: %s", "enabled" if get_auth_enabled() else "disabled")
    init_default_admin()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _startup()
    try:
        yield
    finally:
        from routers.chat import shutdown_active_ai_tasks
        await shutdown_active_ai_tasks()
        from agent.checkpointing import close_agent_checkpointer
        close_agent_checkpointer()
        log_event(
            level="INFO",
            category="system",
            event_type="shutdown",
            message="Backend shutdown completed",
            source="main",
            details={"version": settings.api_version},
        )

# ── Rate limiter ──────────────────────────────────────────────────────────────

def _global_rate_key(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            from auth import verify_token
            username = verify_token(auth.split(" ", 1)[1])
            if username:
                return f"user:{username}"
        except Exception:
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=_global_rate_key, default_limits=["200/minute"])

# ── App ───────────────────────────────────────────────────────────────────────
docs_url = "/docs" if settings.enable_api_docs else None
redoc_url = "/redoc" if settings.enable_api_docs else None
openapi_url = "/openapi.json" if settings.enable_api_docs else None
app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    lifespan=lifespan,
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: use configured origins (never wildcard in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Content-Disposition"],
)

# ── JWT auth middleware ───────────────────────────────────────────────────────
_PUBLIC_PATHS = {"/health", "/info", "/api/auth/login", "/api/auth/config"}


@app.middleware("http")
async def jwt_auth_middleware(request: Request, call_next):
    if (
        request.url.path in _PUBLIC_PATHS
        or request.url.path.startswith("/ssh-setup/")
        or request.method == "OPTIONS"
    ):
        return await call_next(request)

    from auth import get_auth_enabled, verify_token, get_user
    if not get_auth_enabled():
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    token = auth_header.split(" ", 1)[1]
    username = verify_token(token)
    if not username:
        return JSONResponse({"detail": "Invalid or expired token"}, status_code=401)

    user = get_user(username)
    if not user or not user.get("is_active"):
        return JSONResponse({"detail": "Account inactive"}, status_code=401)

    return await call_next(request)


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(chat_router)
app.include_router(models_router)
app.include_router(usage_router)
app.include_router(logs_router)
app.include_router(auth_router)
app.include_router(cron_router)
app.include_router(attachments_router)
app.include_router(backup_router)
app.include_router(systems_router)
app.include_router(ssh_router)


# ── Health / info ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "healthy", "version": settings.api_version}


@app.get("/info")
async def get_info():
    return {
        "title": settings.api_title,
        "version": settings.api_version,
        "model": settings.groq_model,
    }



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.api_host, port=settings.api_port,
                log_level=settings.log_level.lower())
