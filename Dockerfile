# Career Intelligence Kit — API (Sprint 05, B1)
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

RUN playwright install chromium --with-deps

COPY phd_aggregator/ ./phd_aggregator/
WORKDIR /app/phd_aggregator

EXPOSE 8000
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
