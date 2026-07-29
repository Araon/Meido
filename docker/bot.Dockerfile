FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements-bot.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-bot.txt

COPY bot ./bot
COPY meido_settings.py .

CMD ["python", "-m", "bot.bot"]
