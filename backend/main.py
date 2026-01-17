"""EVE Sentinel - Alliance Intel & Recruitment Analysis Tool."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.analyze import router as analyze_router
from backend.api.reports import router as reports_router
from backend.api.webhooks import router as webhooks_router
from backend.database import close_db, init_db
from frontend import router as frontend_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler."""
    # Startup
    print("EVE Sentinel starting up...")
    await init_db()
    print("Database initialized")
    yield
    # Shutdown
    await close_db()
    print("EVE Sentinel shutting down...")


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

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
STATIC_DIR = Path(__file__).parent.parent / "frontend" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Include API routers
app.include_router(analyze_router)
app.include_router(reports_router)
app.include_router(webhooks_router)

# Include frontend router (must be last to avoid path conflicts)
app.include_router(frontend_router)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "healthy", "service": "eve-sentinel"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
