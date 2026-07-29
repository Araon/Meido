from pathlib import Path

import pytest

from downloaderService.contracts import (
    AdapterError,
    DownloadFailed,
    DownloadRequest,
    DownloaderConfigurationError,
)
from downloaderService.router import DownloaderRouter, build_downloader


class FakeBackend:
    def __init__(self, name, *, verify_error=None, download_error=None):
        self.name = name
        self.verify_error = verify_error
        self.download_error = download_error
        self.requests = []

    def verify(self):
        if self.verify_error:
            raise self.verify_error
        return f"{self.name} test-runtime"

    def download(self, request):
        self.requests.append(request)
        partial = request.output_dir / "partial.ts"
        partial.write_bytes(b"partial")
        if self.download_error:
            raise self.download_error
        media = request.output_dir / "result.mp4"
        media.write_bytes(b"video")
        return media


def request(tmp_path):
    return DownloadRequest(
        title="Death Note",
        season=1,
        episode=3,
        output_dir=tmp_path,
        request_id="job-123",
    )


def test_router_uses_next_backend_after_failure(tmp_path):
    primary = FakeBackend("primary", download_error=RuntimeError("blocked"))
    fallback = FakeBackend("fallback")
    router = DownloaderRouter(
        [primary, fallback],
        media_validator=lambda _: None,
    )

    result = router.download(request(tmp_path))

    assert result == tmp_path / "episode.mp4"
    assert result.read_bytes() == b"video"
    assert len(primary.requests) == 1
    assert len(fallback.requests) == 1
    assert not list(tmp_path.glob(".primary-*"))
    assert not list(tmp_path.glob(".fallback-*"))


def test_router_reports_every_backend_failure(tmp_path):
    router = DownloaderRouter(
        [
            FakeBackend("first", download_error=RuntimeError("blocked")),
            FakeBackend("second", download_error=FileNotFoundError("gone")),
        ],
        media_validator=lambda _: None,
    )

    with pytest.raises(DownloadFailed) as raised:
        router.download(request(tmp_path))

    assert [name for name, _ in raised.value.failures] == ["first", "second"]
    assert "first: RuntimeError: blocked" in str(raised.value)
    assert "second: FileNotFoundError: gone" in str(raised.value)


def test_router_verification_keeps_healthy_fallback():
    unavailable = FakeBackend(
        "unavailable",
        verify_error=RuntimeError("missing executable"),
    )
    healthy = FakeBackend("healthy")
    router = DownloaderRouter(
        [unavailable, healthy],
        media_validator=lambda _: None,
    )

    assert router.verify() == ("healthy test-runtime",)
    assert router.available_backends == (unavailable, healthy)


def test_router_verification_fails_when_none_are_healthy():
    router = DownloaderRouter(
        [FakeBackend("broken", verify_error=RuntimeError("missing"))]
    )

    with pytest.raises(DownloadFailed, match="all downloader backends failed"):
        router.verify()


def test_build_downloader_rejects_empty_configuration():
    with pytest.raises(
        DownloaderConfigurationError,
        match="At least one downloader backend",
    ):
        build_downloader(())


def test_router_opens_circuit_after_repeated_temporary_failures(tmp_path):
    clock = [100.0]
    primary = FakeBackend(
        "primary",
        download_error=AdapterError(
            "challenged",
            "Cloudflare challenge",
            retryable=True,
            retry_after=60,
        ),
    )
    fallback = FakeBackend(
        "fallback",
        download_error=AdapterError(
            "not_found",
            "episode unavailable",
        ),
    )
    router = DownloaderRouter(
        [primary, fallback],
        media_validator=lambda _: None,
        failure_threshold=2,
        clock=lambda: clock[0],
    )

    with pytest.raises(DownloadFailed):
        router.download(request(tmp_path))
    with pytest.raises(DownloadFailed):
        router.download(request(tmp_path))
    with pytest.raises(DownloadFailed) as raised:
        router.download(request(tmp_path))

    assert len(primary.requests) == 2
    assert raised.value.failures[0][0] == "primary"
    assert "cooldown active" in str(raised.value.failures[0][1])


def test_router_stops_after_invalid_request(tmp_path):
    primary = FakeBackend(
        "primary",
        download_error=AdapterError(
            "invalid_request",
            "bad season",
        ),
    )
    fallback = FakeBackend("fallback")
    router = DownloaderRouter(
        [primary, fallback],
        media_validator=lambda _: None,
    )

    with pytest.raises(DownloadFailed):
        router.download(request(tmp_path))

    assert len(primary.requests) == 1
    assert fallback.requests == []


def test_router_labels_backend_progress_and_validation(tmp_path):
    backend = FakeBackend("primary")
    updates = []
    router = DownloaderRouter(
        [backend],
        media_validator=lambda _: None,
    )
    download_request = request(tmp_path)
    download_request = DownloadRequest(
        title=download_request.title,
        season=download_request.season,
        episode=download_request.episode,
        output_dir=download_request.output_dir,
        request_id=download_request.request_id,
        progress_callback=updates.append,
    )

    router.download(download_request)
    backend.requests[0].progress_callback(
        {
            "phase": "downloading",
            "percent": 50,
            "detail": "Segment 5/10",
        }
    )

    assert updates[0]["backend"] == "primary"
    assert updates[0]["percent"] == 100
    assert updates[0]["phase"] == "validating"
    assert updates[1]["backend"] == "primary"
    assert updates[1]["percent"] == 50
