FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN python -m pip install --upgrade pip \
    && python -m pip install ".[worker]" \
    && python -m pip check \
    && ffmpeg -version

COPY bot ./bot
COPY downloaderService ./downloaderService
COPY uploaderService ./uploaderService
COPY worker ./worker
COPY meido_settings.py .

CMD ["python", "-m", "worker.main"]
