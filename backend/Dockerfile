FROM python:3.12-slim-bookworm
COPY --from=denoland/deno:bin-2.5.6@sha256:2f5f9d651af33c337767c423a340f76df35e35ff8ff4734210237b9c6fed94c7 /deno /usr/local/bin/deno
COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /uvx /bin/
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
RUN mkdir -p /data && chown app:app /data
ENV PATH="/app/.venv/bin:$PATH" BACKEND_HOST=0.0.0.0 STORAGE_DIR=/data TEMP_DIR=/data/jobs DATABASE_PATH=/data/database/app.db
USER app
RUN deno eval "if (1 + 1 !== 2) throw Error('runtime failed')" \
    && python -c "import yt_dlp_ejs"
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('BACKEND_PORT','8000') + '/api/v1/ready', timeout=3)"
CMD ["sh", "-c", "alembic upgrade head && exec python -m app"]
