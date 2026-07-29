"""Configured downloader selection and fallback orchestration."""

import logging
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time

from downloaderService.contracts import (
    AdapterError,
    DownloadFailed,
    DownloadRequest,
    DownloaderConfigurationError,
    FailureCode,
)
from downloaderService.http_backend import HttpDownloaderBackend


logger = logging.getLogger(__name__)


def build_downloader(
    endpoints,
    *,
    timeout_seconds=1800,
    cooldown_seconds=300,
):
    if not endpoints:
        raise DownloaderConfigurationError(
            "At least one downloader backend must be configured"
        )
    return DownloaderRouter(
        [
            HttpDownloaderBackend(
                name,
                endpoint,
                timeout_seconds=timeout_seconds,
            )
            for name, endpoint in endpoints
        ],
        cooldown_seconds=cooldown_seconds,
    )


class DownloaderRouter:
    CIRCUIT_FAILURE_CODES = {
        FailureCode.CHALLENGED,
        FailureCode.RATE_LIMITED,
        FailureCode.TEMPORARY,
        FailureCode.MISCONFIGURED,
    }
    STOP_CODES = {
        FailureCode.INVALID_REQUEST,
        FailureCode.PERMANENT,
    }

    def __init__(
        self,
        backends,
        *,
        cooldown_seconds=300,
        failure_threshold=2,
        clock=None,
        media_validator=None,
    ):
        self.backends = tuple(backends)
        self.available_backends = self.backends
        self.cooldown_seconds = cooldown_seconds
        self.failure_threshold = failure_threshold
        self.clock = clock or time.monotonic
        self.media_validator = media_validator or validate_media_file
        self._circuits = {}

    def verify(self, *, require_one=True):
        available = []
        descriptions = []
        failures = []
        for backend in self.backends:
            try:
                descriptions.append(backend.verify())
                available.append(backend)
            except Exception as error:
                failures.append((backend.name, error))
                logger.warning(
                    "Downloader backend %s is unavailable: %s",
                    backend.name,
                    error,
                )

        if not available and require_one:
            raise DownloadFailed(failures)
        # Readiness is observational. A sidecar that restarts later must be
        # eligible without restarting the worker.
        self.available_backends = self.backends
        return tuple(descriptions)

    def download(self, request: DownloadRequest) -> Path:
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / "episode.mp4"
        if destination.is_file():
            return destination

        failures = []
        for backend in self.available_backends:
            open_until = self._circuits.get(backend.name, {}).get(
                "open_until",
                0,
            )
            if open_until > self.clock():
                failures.append(
                    (
                        backend.name,
                        AdapterError(
                            "temporary",
                            f"cooldown active for {int(open_until - self.clock())}s",
                            retryable=True,
                            retry_after=max(1, int(open_until - self.clock())),
                        ),
                    )
                )
                continue
            try:
                with TemporaryDirectory(
                    prefix=f".{backend.name}-",
                    dir=output_dir,
                ) as temporary_dir:
                    backend_request = DownloadRequest(
                        title=request.title,
                        season=request.season,
                        episode=request.episode,
                        output_dir=Path(temporary_dir),
                        request_id=request.request_id,
                        language=request.language,
                        max_quality=request.max_quality,
                        sample_seconds=request.sample_seconds,
                        progress_callback=self._backend_progress_callback(
                            request.progress_callback,
                            backend.name,
                        ),
                    )
                    media_file = Path(backend.download(backend_request))
                    if not media_file.is_file():
                        raise FileNotFoundError(
                            f"{backend.name} returned no media file"
                        )
                    self._report_progress(
                        request.progress_callback,
                        backend.name,
                        "validating",
                        100,
                        "Validating media",
                    )
                    self.media_validator(media_file)
                    shutil.move(str(media_file), str(destination))
                self._circuits.pop(backend.name, None)
                logger.info("Downloader backend %s succeeded", backend.name)
                return destination
            except Exception as error:
                failures.append((backend.name, error))
                if isinstance(error, AdapterError):
                    if error.code in self.CIRCUIT_FAILURE_CODES:
                        self._record_circuit_failure(backend.name, error)
                    if error.code in self.STOP_CODES:
                        break
                logger.warning(
                    "Downloader backend %s failed, trying fallback: %s",
                    backend.name,
                    error,
                )

        raise DownloadFailed(failures)

    @staticmethod
    def _backend_progress_callback(callback, backend_name):
        if callback is None:
            return None

        def report(progress):
            callback({"backend": backend_name, **progress})

        return report

    @staticmethod
    def _report_progress(
        callback,
        backend_name,
        phase,
        percent,
        detail,
    ):
        if callback:
            callback(
                {
                    "backend": backend_name,
                    "phase": phase,
                    "percent": percent,
                    "detail": detail,
                }
            )

    def _record_circuit_failure(self, backend_name, error):
        circuit = self._circuits.setdefault(
            backend_name,
            {"failures": 0, "open_until": 0},
        )
        circuit["failures"] += 1
        if circuit["failures"] < self.failure_threshold:
            return
        cooldown = error.retry_after or self.cooldown_seconds
        circuit["open_until"] = self.clock() + cooldown
        logger.warning(
            "Downloader backend %s circuit opened for %ss",
            backend_name,
            cooldown,
        )


def validate_media_file(media_file):
    """Require a decodable video stream before an adapter can succeed."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(media_file),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AdapterError(
            "temporary",
            f"media validation failed: {error}",
            retryable=True,
        ) from error
    if "video" not in result.stdout.split():
        raise AdapterError(
            "temporary",
            "media validation found no video stream",
            retryable=True,
        )
