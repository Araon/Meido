"""Stable contracts shared by the worker and downloader adapters."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class DownloadRequest:
    title: str
    season: int
    episode: int
    output_dir: Path
    request_id: str
    language: str = "sub"
    max_quality: int = 1080
    sample_seconds: int | None = None
    progress_callback: Callable[[dict], None] | None = None


class DownloaderConfigurationError(ValueError):
    """Raised when downloader backend configuration is invalid."""


class FailureCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    UNSUPPORTED = "unsupported"
    CHALLENGED = "challenged"
    RATE_LIMITED = "rate_limited"
    TEMPORARY = "temporary"
    MISCONFIGURED = "misconfigured"
    PERMANENT = "permanent"


class AdapterError(RuntimeError):
    """Typed failure returned by a downloader sidecar."""

    def __init__(
        self,
        code,
        detail,
        *,
        retryable=False,
        retry_after=None,
    ):
        try:
            self.code = FailureCode(code)
        except ValueError:
            self.code = FailureCode.TEMPORARY
        self.retryable = bool(retryable)
        self.retry_after = (
            int(retry_after) if retry_after not in (None, "") else None
        )
        super().__init__(detail)


class DownloadFailed(RuntimeError):
    """Raised after every configured downloader backend has failed."""

    def __init__(self, failures):
        self.failures = tuple(failures)
        details = "; ".join(
            f"{backend}: {type(error).__name__}: {error}"
            for backend, error in self.failures
        )
        super().__init__(f"all downloader backends failed ({details})")
