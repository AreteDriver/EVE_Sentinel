# EVE Sentinel - Multi-stage Docker Build
# Optimized for production deployment

# Build stage
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Production stage
FROM python:3.12-slim as production

WORKDIR /app

# Install runtime dependencies for WeasyPrint
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r sentinel && useradd -r -g sentinel sentinel

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Create directories for data and ML models
RUN mkdir -p /app/data /app/backend/data/models && chown -R sentinel:sentinel /app

# Switch to non-root user
USER sentinel

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_URL=sqlite+aiosqlite:///./data/sentinel.db \
    PORT=8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:${PORT}/health')" || exit 1

# Expose port
EXPOSE ${PORT}

# Run the application
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
