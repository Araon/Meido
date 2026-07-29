FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml .
RUN python -m pip install --upgrade pip \
    && python -m pip install ".[bot]" \
    && python -m pip check

COPY bot ./bot
COPY meido_settings.py .

CMD ["python", "-m", "bot.bot"]
