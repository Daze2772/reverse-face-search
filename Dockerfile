# ────────────────────────────────────────────────────────────────────────────
#  Reverse Face Search v2 — Production Dockerfile
#  Two-stage build keeps the runtime image lean.
#
#  Build slim: docker build -t rfs:slim .
#  Build with face verification:
#      docker build --build-arg WITH_FACE=true -t rfs:face .
# ────────────────────────────────────────────────────────────────────────────

# ─── Stage 1: build ───────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ARG WITH_FACE=false

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev libxslt1-dev \
    libjpeg-dev zlib1g-dev libfreetype6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

# Strip face deps unless WITH_FACE=true (saves ~700 MB ONNX bloat).
RUN if [ "$WITH_FACE" = "true" ]; then \
        echo "Installing with face-embedding deps"; \
        pip install --prefix=/install -r requirements.txt; \
    else \
        echo "Installing slim (no face-embedding deps)"; \
        sed -e 's/^insightface/# insightface/' \
            -e 's/^onnxruntime/# onnxruntime/' \
            -e 's/^opencv-python-headless/# opencv-python-headless/' \
            requirements.txt > slim-requirements.txt; \
        pip install --prefix=/install -r slim-requirements.txt; \
    fi


# ─── Stage 2: runtime ─────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ARG WITH_FACE=false
ENV WITH_FACE=$WITH_FACE \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libgtk-3-0 libxshmfence1 fonts-liberation \
    ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

# OpenCV needs libGL when face verification is enabled.
RUN if [ "$WITH_FACE" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            libgl1 libglib2.0-0 \
        && rm -rf /var/lib/apt/lists/*; \
    fi

COPY --from=builder /install /usr/local

RUN python -m playwright install --with-deps chromium

RUN useradd --create-home --uid 1000 rfs

WORKDIR /app
COPY --chown=rfs:rfs src ./src
COPY --chown=rfs:rfs templates ./templates
COPY --chown=rfs:rfs static ./static
COPY --chown=rfs:rfs config.yaml ./config.yaml
COPY --chown=rfs:rfs .env.example ./.env.example

RUN mkdir -p uploads logs dossiers data cache reports \
    && chown -R rfs:rfs /app

USER rfs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "src.main"]
