#!/usr/bin/env python3
"""Upload completed media to the bot through a Telegram user account."""

import asyncio
from getpass import getpass
import json
import logging
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from meido_settings import load_settings
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import DocumentAttributeVideo


logger = logging.getLogger(__name__)


async def authorized_client(settings):
    settings.session_root.mkdir(parents=True, exist_ok=True)
    session_path = settings.session_root / settings.session_name
    client = TelegramClient(
        str(session_path),
        settings.api_id,
        settings.api_hash,
    )
    await client.connect()
    if not await client.is_user_authorized():
        await client.send_code_request(settings.phone)
        code = input("Enter the Telegram login code: ").strip()
        try:
            await client.sign_in(settings.phone, code)
        except SessionPasswordNeededError:
            await client.sign_in(password=getpass("Telegram 2FA password: "))
    return client


async def authorize(settings):
    client = await authorized_client(settings)
    try:
        logger.info("Telegram worker session is authorized")
    finally:
        await client.disconnect()


def bot_id_from_token(bot_token):
    try:
        return int(bot_token.partition(":")[0])
    except (TypeError, ValueError) as error:
        raise ValueError("TELEGRAM_BOT_TOKEN has an invalid format") from error


async def resolve_bot_recipient(
    client,
    configured_username,
    expected_bot_id=None,
):
    """Resolve the configured peer and reject user accounts."""
    recipient = await client.get_entity(configured_username)
    if not getattr(recipient, "bot", False):
        resolved_username = getattr(recipient, "username", None) or "<unknown>"
        raise ValueError(
            "TELEGRAM_BOT_USERNAME must identify a bot account; "
            f"@{resolved_username} is a Telegram user"
        )
    if expected_bot_id is not None and recipient.id != expected_bot_id:
        resolved_username = getattr(recipient, "username", None) or "<unknown>"
        raise ValueError(
            "TELEGRAM_BOT_USERNAME does not match TELEGRAM_BOT_TOKEN; "
            f"@{resolved_username} belongs to a different bot"
        )
    logger.info(
        "Telegram upload recipient verified: @%s",
        getattr(recipient, "username", configured_username),
    )
    return recipient


def video_attribute(file_path):
    """Read real video metadata so Telegram classifies the upload as video."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height:format=duration",
                "-of",
                "json",
                str(file_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        metadata = json.loads(result.stdout)
        stream = metadata["streams"][0]
        duration = float(metadata.get("format", {}).get("duration") or 0)
        return DocumentAttributeVideo(
            duration=duration,
            w=int(stream["width"]),
            h=int(stream["height"]),
            supports_streaming=True,
        )
    except Exception as error:
        logger.warning("Could not probe video metadata: %s", error)
        return DocumentAttributeVideo(
            duration=0,
            w=0,
            h=0,
            supports_streaming=True,
        )


async def upload_video_with_client(
    client,
    recipient,
    file_path,
    job_id,
    progress_callback=None,
):
    file_path = Path(file_path).resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    def report_upload_progress(current, total):
        if total <= 0:
            return
        percent = current / total * 100
        logger.info("Uploaded %.1f%%", percent)
        if progress_callback:
            progress_callback(
                {
                    "phase": "uploading",
                    "percent": percent,
                    "detail": "Uploading to Telegram",
                }
            )

    return await client.send_file(
        recipient,
        str(file_path),
        caption=f"meido:{job_id}",
        attributes=[video_attribute(file_path)],
        progress_callback=report_upload_progress,
        part_size_kb=512,
        supports_streaming=True,
    )


async def upload_video(
    file_path,
    job_id,
    settings,
    progress_callback=None,
):
    client = await authorized_client(settings)
    try:
        recipient = await resolve_bot_recipient(
            client,
            settings.bot_username,
            bot_id_from_token(settings.bot_token),
        )
        return await upload_video_with_client(
            client,
            recipient,
            file_path,
            job_id,
            progress_callback=progress_callback,
        )
    finally:
        await client.disconnect()


async def main(argv):
    settings = load_settings(require_uploader=True)
    if len(argv) == 2 and argv[1] == "--authorize":
        await authorize(settings)
        return
    if len(argv) != 3:
        raise ValueError(
            "Usage: python -m uploaderService.main --authorize | "
            "<file_path> <job_id>"
        )
    await upload_video(argv[1], argv[2], settings)


if __name__ == "__main__":
    logging.basicConfig(
        format="%(levelname)s - %(asctime)s - %(name)s - %(message)s",
        level=logging.INFO,
    )
    asyncio.run(main(sys.argv))
