"""Generic client for versioned HTTP downloader sidecars."""

import json
from pathlib import Path
from threading import Event, Thread
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from downloaderService.contracts import AdapterError, DownloadRequest


class HttpDownloaderBackend:
    def __init__(self, name, endpoint, *, timeout_seconds=1800):
        self.name = name
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def verify(self):
        request = Request(
            f"{self.endpoint}/health/ready",
            headers={"accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.load(response)
        except (OSError, URLError, ValueError) as error:
            raise AdapterError(
                "temporary",
                f"{self.name} readiness check failed: {error}",
                retryable=True,
            ) from error

        providers = payload.get("providers", [])
        if providers and self.name not in providers:
            raise AdapterError(
                "misconfigured",
                f"{self.name} is not enabled by {self.endpoint}",
            )
        runtime = payload.get("runtime", "HTTP sidecar")
        return f"{self.name} via {runtime}"

    def download(self, request: DownloadRequest) -> Path:
        payload = json.dumps(
            {
                "contract_version": 1,
                "request_id": request.request_id,
                "backend": self.name,
                "title": request.title,
                "season": request.season,
                "episode": request.episode,
                "language": request.language,
                "max_quality": request.max_quality,
                "sample_seconds": request.sample_seconds,
            }
        ).encode("utf-8")
        http_request = Request(
            f"{self.endpoint}/v1/download",
            data=payload,
            method="POST",
            headers={
                "accept": "video/mp4, application/problem+json",
                "content-type": "application/json",
            },
        )
        output_path = Path(request.output_dir) / "download.part"
        output_path.unlink(missing_ok=True)
        stop_progress = Event()
        progress_thread = None
        if request.progress_callback:
            progress_thread = Thread(
                target=self._poll_progress,
                args=(
                    request.request_id,
                    request.progress_callback,
                    stop_progress,
                ),
                daemon=True,
                name=f"progress-{self.name}",
            )
            progress_thread.start()

        try:
            with urlopen(
                http_request,
                timeout=self.timeout_seconds,
            ) as response, output_path.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        except HTTPError as error:
            output_path.unlink(missing_ok=True)
            raise self._adapter_error(error) from error
        except (OSError, URLError, TimeoutError) as error:
            output_path.unlink(missing_ok=True)
            raise AdapterError(
                "temporary",
                f"{self.name} request failed: {error}",
                retryable=True,
            ) from error
        finally:
            stop_progress.set()
            if progress_thread:
                progress_thread.join(timeout=2)

        if not output_path.is_file() or output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)
            raise AdapterError(
                "temporary",
                f"{self.name} returned an empty response",
                retryable=True,
            )
        return output_path

    def _poll_progress(self, request_id, callback, stop_event):
        query = urlencode({"request_id": request_id})
        progress_url = f"{self.endpoint}/v1/progress?{query}"
        previous = None
        while not stop_event.is_set():
            try:
                with urlopen(progress_url, timeout=5) as response:
                    progress = json.load(response)
                signature = (
                    progress.get("phase"),
                    progress.get("percent"),
                    progress.get("detail"),
                )
                if signature != previous:
                    callback(progress)
                    previous = signature
            except (HTTPError, OSError, URLError, ValueError):
                # A 404 is expected before the POST handler registers the job.
                pass
            stop_event.wait(1)

    def _adapter_error(self, error):
        try:
            payload = json.loads(error.read(1024 * 1024).decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            payload = {}
        return AdapterError(
            payload.get("code", "temporary"),
            payload.get("detail", f"{self.name} returned HTTP {error.code}"),
            retryable=payload.get("retryable", error.code >= 500),
            retry_after=payload.get("retry_after"),
        )
