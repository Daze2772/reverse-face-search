# ────────────────────────────────────────────────────────────────────────────
#  Reverse Face Search v2 — Production Dockerfile
#  Two-stage build keeps the runtime image lean.
# ────────────────────────────────────────────────────────────────────────────

# ─── Stage 1: build ───────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# System deps required for some wheels (lxml, Pillow, reportlab, opencv).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev libxslt1-dev \
    libjpeg-dev zlib1g-dev libfreetype6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --prefix=/install -r requirements.txt


# ─── Stage 2: runtime ─────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DEBIAN_FRONTEND=noninteractive

# Playwright Chromium runtime dependencies.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libgtk-3-0 libxshmfence1 fonts-liberation \
    ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /install /usr/local

# Install Playwright Chromium binary (one-time, baked into image).
RUN python -m playwright install --with-deps chromium \
    && python -m playwright install-deps chromium

# Maigret needs a writable home for its sites database.
RUN useradd --create-home --uid 1000 rfs

WORKDIR /app
COPY --chown=rfs:rfs src ./src
COPY --chown=rfs:rfs templates ./templates
COPY --chown=rfs:rfs static ./static
COPY --chown=rfs:rfs config.yaml ./config.yaml
COPY --chown=rfs:rfs .env.example ./.env.example

# Writable data directories (mounted as volumes in prod).
RUN mkdir -p uploads logs dossiers data cache reports \
    && chown -R rfs:rfs /app

USER rfs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "src.main"]
