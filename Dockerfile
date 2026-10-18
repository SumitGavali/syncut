FROM python:3.11-slim

# System deps (must run as root, before switching user)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg build-essential \
    && rm -rf /var/lib/apt/lists/*

# Non-root user required by Spaces
RUN useradd -m -u 1000 user
USER user
ENV PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

ENV PORT=7860
EXPOSE 7860

# ONE worker: SESSIONS is an in-memory dict, so multiple workers
# would each have their own copy and break the sync -> export flow.
CMD gunicorn app:app --bind 0.0.0.0:7860 --timeout 600 --workers 1 --threads 4