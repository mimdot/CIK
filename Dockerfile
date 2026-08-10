# Career Intelligence Kit — API (Sprint 05, B1; hardened Sprint 10, A2).
# Build: docker build -t cik-api .
FROM python:3.11-slim

WORKDIR /app

# System deps: curl for healthchecks, plus the libraries Playwright's
# Chromium build needs (anti-bot fallback for crawled sources).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libnss3 libatk-bridge2.0-0 libdrm2 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

COPY phd_aggregator/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Playwright browsers land in a shared, world-readable location so the
# non-root runtime user (below) can find them.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install chromium --with-deps

COPY phd_aggregator/ ./phd_aggregator/
WORKDIR /app/phd_aggregator

# Non-root runtime (Sprint 10, A2). The /data volume (DB, cache, profiles,
# seed files) must be writable by this user; compose mounts it and the image
# chowns it here.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app \
    && mkdir -p /data && chown -R appuser:appuser /data
USER appuser

# Number of uvicorn workers. Keep at 1 unless you run Redis AND set
# CIK_SCHEDULER_ENABLED=0 on the extra workers (see docs/DEPLOYMENT.md).
ENV API_WORKERS=1

EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port 8000 --workers ${API_WORKERS}"]
