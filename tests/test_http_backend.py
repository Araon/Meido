import io
import json
from threading import Event
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from downloaderService.contracts import AdapterError, DownloadRequest
from downloaderService.http_backend import HttpDownloaderBackend


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def request(tmp_path):
    return DownloadRequest(
        title="Death Note",
        season=1,
        episode=3,
        output_dir=tmp_path,
        request_id="job-123",
        sample_seconds=10,
    )


def test_http_backend_streams_response_to_isolated_directory(tmp_path):
    backend = HttpDownloaderBackend(
        "animeparadise",
        "http://downloader:8080",
    )

    with patch(
        "downloaderService.http_backend.urlopen",
        return_value=FakeResponse(b"video-bytes"),
    ) as open_url:
        result = backend.download(request(tmp_path))

    sent = json.loads(open_url.call_args.args[0].data)
    assert sent["contract_version"] == 1
    assert sent["backend"] == "animeparadise"
    assert sent["title"] == "Death Note"
    assert sent["season"] == 1
    assert sent["episode"] == 3
    assert sent["sample_seconds"] == 10
    assert result.read_bytes() == b"video-bytes"


def test_http_backend_preserves_typed_problem_response(tmp_path):
    problem = json.dumps(
        {
            "code": "challenged",
            "detail": "Cloudflare challenge",
            "retryable": True,
            "retry_after": 900,
        }
    ).encode()
    error = HTTPError(
        "http://downloader:8080/v1/download",
        503,
        "Service Unavailable",
        {},
        io.BytesIO(problem),
    )
    backend = HttpDownloaderBackend(
        "animeparadise",
        "http://downloader:8080",
    )

    with patch(
        "downloaderService.http_backend.urlopen",
        side_effect=error,
    ), pytest.raises(AdapterError) as raised:
        backend.download(request(tmp_path))

    assert raised.value.code.value == "challenged"
    assert raised.value.retryable is True
    assert raised.value.retry_after == 900


def test_http_backend_polls_distinct_progress_updates():
    backend = HttpDownloaderBackend(
        "animeparadise",
        "http://downloader:8080",
    )
    stop = Event()
    updates = []

    def record(progress):
        updates.append(progress)
        stop.set()

    response = FakeResponse(
        json.dumps(
            {
                "phase": "downloading",
                "percent": 50,
                "detail": "Segment 5/10",
            }
        ).encode()
    )
    with patch(
        "downloaderService.http_backend.urlopen",
        return_value=response,
    ):
        backend._poll_progress("job-123", record, stop)

    assert updates == [
        {
            "phase": "downloading",
            "percent": 50,
            "detail": "Segment 5/10",
        }
    ]
