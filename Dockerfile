FROM python:3.12-slim

# ── System libraries (Playwright Chromium needs these) ────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates git \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libcairo2 libxshmfence1 \
    libx11-6 libxext6 libxrender1 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python dependencies ───────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Playwright Chromium ───────────────────────────────────────────────────────
RUN playwright install chromium
RUN playwright install-deps chromium

# ── Application code ──────────────────────────────────────────────────────────
COPY . .

# Persistent data folders (SQLite + reports)
RUN mkdir -p data reports output

EXPOSE 8000

# Headless mode: no --visible flag (cloud has no display)
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8000"]
