"""Exercise configured downloader backends without Redis or Telegram."""

import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from downloaderService.contracts import DownloadFailed, DownloadRequest
from downloaderService.router import build_downloader
from meido_settings import load_settings


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Download one episode through the configured backend router."
    )
    parser.add_argument("title")
    parser.add_argument("episode", type=int)
    parser.add_argument("--season", type=int, default=1)
    parser.add_argument(
        "--backend",
        help="Test only one configured backend instead of the fallback chain",
    )
    parser.add_argument(
        "--seconds",
        type=int,
        default=10,
        help="Limit compatible backends to a short sample (default: 10)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Download the complete episode instead of a short sample",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    endpoints = settings.downloader_endpoints
    if args.backend:
        endpoints = tuple(
            endpoint
            for endpoint in endpoints
            if endpoint[0] == args.backend.lower()
        )
        if not endpoints:
            configured = ", ".join(
                name for name, _ in settings.downloader_endpoints
            )
            parser.error(
                f"unknown backend {args.backend!r}; configured: {configured}"
            )
    downloader = build_downloader(
        endpoints,
        timeout_seconds=settings.downloader_timeout_seconds,
        cooldown_seconds=settings.downloader_cooldown_seconds,
    )
    descriptions = downloader.verify()
    print("Healthy downloader adapters: " + ", ".join(descriptions))

    with TemporaryDirectory(prefix="meido-downloader-smoke-") as directory:
        last_progress = [None]

        def show_progress(progress):
            current = (
                progress.get("backend"),
                progress.get("phase"),
                int(float(progress.get("percent", 0))),
            )
            if current == last_progress[0]:
                return
            last_progress[0] = current
            backend, phase, percent = current
            print(f"[{backend or 'router'}] {phase}: {percent}%")

        try:
            media_file = downloader.download(
                DownloadRequest(
                    title=args.title,
                    season=args.season,
                    episode=args.episode,
                    output_dir=Path(directory),
                    request_id=f"smoke-{uuid4().hex}",
                    sample_seconds=None if args.full else args.seconds,
                    progress_callback=show_progress,
                )
            )
        except DownloadFailed as error:
            print(f"Downloader smoke test failed: {error}", file=sys.stderr)
            return 1

        size = media_file.stat().st_size
        print(f"Downloader smoke test passed: {media_file.name} ({size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
