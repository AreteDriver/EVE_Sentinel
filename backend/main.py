"""EVE Sentinel - Alliance Intel & Recruitment Analysis Tool."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from backend.api.admin import router as admin_router
from backend.api.analyze import router as analyze_router
from backend.api.auth import router as auth_router
from backend.api.ml import router as ml_router
from backend.api.reports import router as reports_router
from backend.api.shares import router as shares_router
from backend.api.watchlist import router as watchlist_router
from backend.api.webhooks import router as webhooks_router
from backend.cache import cache
from backend.config import settings
from backend.database import close_db, init_db
from backend.logging_config import get_logger, setup_logging
from backend.rate_limit import limiter, rate_limit_exceeded_handler
from frontend import router as frontend_router

# Initialize logging
setup_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler."""
    # Startup
    logger.info("EVE Sentinel starting up...")
    await init_db()
    logger.info("Database initialized")
    await cache.connect()
    yield
    # Shutdown
    await cache.close()
    await close_db()
    logger.info("EVE Sentinel shutting down...")


app = FastAPI(
    title="EVE Sentinel",
    description="""
    Alliance Intel & Recruitment Analysis Tool for EVE Online.

    Analyze ESI data to produce risk assessments for recruitment.
    Identifies playstyle, detects alts, and flags potential security risks.

    ## Features

    - **Risk Scoring**: Green/Yellow/Red flag system
    - **Corp History Analysis**: Detect spy corps, rapid hopping
    - **Alt Detection**: Identify likely alt characters
    - **Killboard Analysis**: AWOX detection, activity patterns
    - **Playstyle Profiling**: Classify pilot behavior

    ## Quick Start

    1. Use `/api/v1/quick-check/{character_id}` for fast screening
    2. Use `/api/v1/analyze/{character_id}` for full analysis
    3. Use `/api/v1/analyze/batch` for bulk processing
    """,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Session middleware for SSO authentication
# In production, use a proper secret key from environment
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    session_cookie="sentinel_session",
    max_age=86400,  # 24 hours
    same_site="lax",
    https_only=False,  # Set to True in production with HTTPS
)

# CORS middleware - configure via CORS_ORIGINS env var
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Mount static files
STATIC_DIR = Path(__file__).parent.parent / "frontend" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Include API routers
app.include_router(auth_router)
app.include_router(analyze_router)
app.include_router(reports_router)
app.include_router(shares_router)
app.include_router(watchlist_router)
app.include_router(webhooks_router)
app.include_router(ml_router)
app.include_router(admin_router)

# Include frontend router (must be last to avoid path conflicts)
app.include_router(frontend_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "eve-sentinel"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
