# AcceptGuard web app: FastAPI + Gemini (server-side) + Tesseract OCR.
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY eval/data ./eval/data
RUN uv sync --frozen --no-dev

RUN useradd --create-home app && mkdir -p /app/.cache && chown -R app /app/.cache
USER app
EXPOSE 8000
HEALTHCHECK CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health')"
CMD ["sh", "-c", "uv run --no-sync uvicorn acceptguard.web.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
