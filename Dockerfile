FROM python:3.11-slim AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
COPY synccut ./synccut
RUN pip install --no-cache-dir --prefix=/install --no-deps .

FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system synccut \
    && useradd --system --gid synccut --create-home synccut \
    && mkdir -p /var/lib/synccut /var/data \
    && chown -R synccut:synccut /var/lib/synccut /var/data

WORKDIR /app
COPY --from=builder /install /install
COPY --chown=synccut:synccut synccut /app/synccut

ENV PATH="/install/bin:${PATH}" \
    PYTHONPATH="/app:/install/lib/python3.11/site-packages" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    SYNCCUT_DATA_DIR=/var/lib/synccut

USER synccut
EXPOSE 7860

CMD ["sh", "-c", "gunicorn 'synccut.api.factory:create_app()' --bind 0.0.0.0:${PORT:-7860} --timeout 600 --workers 1 --threads 4"]
