"""Central configuration for every Meido process."""

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"


class SettingsError(ValueError):
    """Raised when required application settings are missing or invalid."""


def _optional_int(name):
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise SettingsError(f"{name} must be an integer") from error


def _bot_username():
    value = os.getenv("TELEGRAM_BOT_USERNAME", "").strip()
    if value and not value.startswith("@"):
        value = f"@{value}"
    return value or None


def _positive_int(name, default):
    value = os.getenv(name, str(default)).strip()
    try:
        parsed = int(value)
    except ValueError as error:
        raise SettingsError(f"{name} must be an integer") from error
    if parsed < 1:
        raise SettingsError(f"{name} must be greater than zero")
    return parsed


def _downloader_endpoints():
    raw = os.getenv(
        "DOWNLOADER_ENDPOINTS",
        (
            "animeparadise=http://downloader-anime-sdk:8080,"
            "gogoanime=http://downloader-anime-sdk:8080,"
            "anikoto=http://downloader-anime-sdk:8080,"
            "megaplay=http://downloader-anime-sdk:8080"
        ),
    )
    endpoints = []
    names = set()
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        name, separator, endpoint = entry.partition("=")
        name = name.strip().lower()
        endpoint = endpoint.strip().rstrip("/")
        parsed = urlparse(endpoint)
        if (
            not separator
            or not name
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
        ):
            raise SettingsError(
                "DOWNLOADER_ENDPOINTS entries must use name=http(s)://host"
            )
        if name in names:
            raise SettingsError(
                f"DOWNLOADER_ENDPOINTS contains duplicate backend: {name}"
            )
        names.add(name)
        endpoints.append((name, endpoint))
    if not endpoints:
        raise SettingsError("DOWNLOADER_ENDPOINTS cannot be empty")
    return tuple(endpoints)


@dataclass(frozen=True)
class Settings:
    bot_token: str | None
    agent_user_id: int | None
    api_id: int | None
    api_hash: str | None
    phone: str | None
    bot_username: str | None
    session_name: str
    session_root: Path
    redis_url: str
    download_root: Path
    downloader_endpoints: tuple[tuple[str, str], ...]
    downloader_timeout_seconds: int
    downloader_cooldown_seconds: int
    download_concurrency: int
    downloader_max_job_attempts: int
    downloader_retry_delay_seconds: int
    upload_concurrency: int
    upload_max_job_attempts: int
    upload_retry_delay_seconds: int
    log_level: str


def load_settings(
    *,
    require_bot=False,
    require_worker=False,
    require_uploader=False,
):
    """Load the shared `.env`, with real environment variables taking priority."""
    load_dotenv(ENV_FILE, override=False)

    settings = Settings(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or None,
        agent_user_id=_optional_int("TELEGRAM_AGENT_USER_ID"),
        api_id=_optional_int("TELEGRAM_API_ID"),
        api_hash=os.getenv("TELEGRAM_API_HASH", "").strip() or None,
        phone=os.getenv("TELEGRAM_PHONE", "").strip() or None,
        bot_username=_bot_username(),
        session_name=os.getenv("TELEGRAM_SESSION_NAME", "meido_agent").strip()
        or "meido_agent",
        session_root=Path(
            os.getenv(
                "TELEGRAM_SESSION_ROOT",
                str(PROJECT_ROOT / ".sessions"),
            )
        ).expanduser(),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0").strip(),
        download_root=Path(
            os.getenv("DOWNLOAD_ROOT", str(PROJECT_ROOT / "downloads"))
        ).expanduser(),
        downloader_endpoints=_downloader_endpoints(),
        downloader_timeout_seconds=_positive_int(
            "DOWNLOADER_TIMEOUT_SECONDS",
            1800,
        ),
        downloader_cooldown_seconds=_positive_int(
            "DOWNLOADER_COOLDOWN_SECONDS",
            300,
        ),
        download_concurrency=_positive_int(
            "DOWNLOAD_CONCURRENCY",
            2,
        ),
        downloader_max_job_attempts=_positive_int(
            "DOWNLOADER_MAX_JOB_ATTEMPTS",
            3,
        ),
        downloader_retry_delay_seconds=_positive_int(
            "DOWNLOADER_RETRY_DELAY_SECONDS",
            60,
        ),
        upload_concurrency=_positive_int(
            "UPLOAD_CONCURRENCY",
            2,
        ),
        upload_max_job_attempts=_positive_int(
            "UPLOAD_MAX_JOB_ATTEMPTS",
            3,
        ),
        upload_retry_delay_seconds=_positive_int(
            "UPLOAD_RETRY_DELAY_SECONDS",
            60,
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
    )

    missing = []
    if require_bot:
        if not settings.bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if settings.agent_user_id is None:
            missing.append("TELEGRAM_AGENT_USER_ID")
    if require_uploader and not settings.bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if require_worker or require_uploader:
        for name, value in (
            ("TELEGRAM_API_ID", settings.api_id),
            ("TELEGRAM_API_HASH", settings.api_hash),
            ("TELEGRAM_PHONE", settings.phone),
            ("TELEGRAM_BOT_USERNAME", settings.bot_username),
        ):
            if value is None:
                missing.append(name)

    if missing:
        raise SettingsError(
            "Missing required settings: " + ", ".join(sorted(set(missing)))
        )
    return settings
