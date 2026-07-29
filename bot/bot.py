#!/usr/bin/env python3

import logging
import sys
import socket
from pathlib import Path

# Support both `python -m bot.bot` and direct script execution.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)
from meido_settings import load_settings
from bot.commands import (
    showhelp,
    parse_search_query,
    normalize_series_name,
    validate_search_query,
)
from bot.store import initialize_store

BOT_VERSION = 0.1
SETTINGS = None
STORE = None

# enabling Logging
logging.basicConfig(
    format='%(levelname)s - %(asctime)s - %(name)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
# HTTPX logs Telegram API URLs, which contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)

PHASE_LABELS = {
    "starting": "Starting",
    "searching": "Searching",
    "episodes": "Loading episodes",
    "resolving": "Resolving stream",
    "downloading": "Downloading",
    "muxing": "Preparing MP4",
    "prepared": "Download prepared",
    "streaming": "Transferring to worker",
    "complete": "Download complete",
    "validating": "Validating media",
    "upload_queued": "Waiting for upload slot",
    "uploading": "Uploading to Telegram",
    "awaiting_bot": "Waiting for bot confirmation",
}


def progress_bar(percent, width=10):
    completed = round(max(0, min(100, percent)) / 100 * width)
    return "█" * completed + "░" * (width - completed)


def format_progress_message(job, progress):
    percent = max(0, min(100, int(progress.get("percent", 0))))
    phase = progress.get("phase", "downloading")
    label = PHASE_LABELS.get(phase, phase.replace("_", " ").title())
    title = job.get("series_name", "Anime")
    season = int(job.get("season_id", 0))
    episode = int(job.get("episode_id", 0))
    lines = [
        f"{title} S{season:02d}E{episode:02d}",
        f"{label}: [{progress_bar(percent)}] {percent}%",
    ]
    backend = progress.get("backend")
    if backend:
        lines.append(f"Source: {backend}")
    detail = progress.get("detail")
    if detail and detail != label:
        lines.append(str(detail)[:120])
    lines.append(f"Job: {job.get('job_id', '')[:8]}")
    return "\n".join(lines)


async def edit_progress_messages(context, job_id, text):
    for chat_id, message_id in STORE.get_progress_messages(job_id).items():
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
            )
        except BadRequest as error:
            if "message is not modified" not in str(error).lower():
                logger.warning(
                    "Could not edit progress message for job %s: %s",
                    job_id,
                    error,
                )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        f"Thanks for using Araon Bot({BOT_VERSION})\n"
        "This is a alpha built so expect delayed response and many bugs\n"
        "If you spot any issue feel free to reach out"
    )
    await update.message.reply_text(message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = showhelp()
    await update.message.reply_text(text)


async def getanime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return a cached episode or queue it for the media worker."""
    logger.info('download function is called!')

    chat_id = update.effective_chat.id
    raw_user_input = update.message.text or ""
    user_input = raw_user_input.partition(" ")[2].strip()

    if user_input:
        userdata = parse_search_query(user_input)
        validation_error = validate_search_query(userdata)
        if validation_error:
            await update.message.reply_text(
                f"{validation_error}\n"
                "Usage: /getanime <name>, <season>, <episode>"
            )
            return
        
        # Normalize series name to create consistent series_key
        series_name = userdata.get('series_name')
        series_key = normalize_series_name(series_name)
        season_id = userdata.get('season_id')
        episode_id = userdata.get('episode_id')

        reply_msg = (
            f"Checking Internal Db\n"
            f"Anime: {series_name}\n"
            f"Season: {season_id}\n"
            f"Episode: {episode_id}"
        )
        await update.message.reply_text(reply_msg)
        logger.info("episode_request=%s", userdata)

        anime_name = STORE.get_episode(series_key, season_id, episode_id)
        if anime_name:
            logger.info("Found cached episode %s", series_key)
            try:
                if anime_name.get("file_id"):
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=anime_name.get("file_id"),
                        supports_streaming=True,
                        read_timeout=120,
                        write_timeout=120
                    )
                    STORE.increment_episode_queries(
                        series_key,
                        season_id,
                        episode_id,
                    )
                    return  # Exit early since we found and sent the video
            except Exception as e:
                logger.error(f"Error sending video: {e}")
                logger.info("Cached file failed; queuing a replacement")
                await update.message.reply_text("Error sending cached video. Re-downloading...")

        try:
            job_id, created = STORE.enqueue_episode(
                series_key=series_key,
                series_name=series_name,
                season_id=season_id,
                episode_id=episode_id,
                chat_id=chat_id,
            )
            if created:
                message = (
                    f"Queued {series_name} S{season_id:02d}E{episode_id:02d}.\n"
                    f"Job: {job_id[:8]}"
                )
            else:
                message = (
                    "That episode is already being prepared. "
                    "You will receive it when the job finishes."
                )
            progress_message = await update.message.reply_text(message)
            STORE.set_progress_message(
                job_id,
                chat_id,
                progress_message.message_id,
            )
        except Exception:
            logger.exception("Could not enqueue episode")
            await update.message.reply_text(
                "The media queue is unavailable. Please retry shortly."
            )

    else:
        await update.message.reply_text("Please refer to /help")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log Errors caused by Updates."""
    logger.error(
        'Update "%s" caused error "%s"',
        update, context.error
    )
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text("Something has went wrong!, Please retry")
        except Exception:
            pass  # Ignore errors when trying to send error message


async def check_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    '''
    This function is important as this checks for all the files uploaded
    to the telegram server and returns a file id
    '''
    logger.info('check_document function is called!')
    user_id = update.message.from_user.id

    if user_id == SETTINGS.agent_user_id:
        media = update.message.video
        if (
            media is None
            and update.message.document
            and (update.message.document.mime_type or "").startswith("video/")
        ):
            media = update.message.document
        if media is None:
            logger.warning('Received message without video media')
            return

        file_id = media.file_id
        caption = update.message.caption

        if not caption or not caption.startswith("meido:"):
            logger.warning('Received video without proper caption format')
            return

        try:
            job_id = caption.partition(":")[2].strip()
            progress_messages = STORE.get_progress_messages(job_id)
            waiters = STORE.complete_job(job_id, file_id)
            for chat_id in waiters:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=file_id,
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                )
            job = STORE.get_job(job_id) or {}
            ready_text = (
                f"{job.get('series_name', 'Anime')} "
                f"S{int(job.get('season_id', 0)):02d}"
                f"E{int(job.get('episode_id', 0)):02d}\n"
                "Ready ✅"
            )
            for chat_id, message_id in progress_messages.items():
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=ready_text,
                    )
                except BadRequest:
                    logger.warning(
                        "Could not mark progress message ready for job %s",
                        job_id,
                    )
            STORE.clear_progress_messages(job_id)
        except Exception:
            logger.exception("Error completing uploaded job")


async def debug_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info('debug_message function is called!')


async def process_worker_events(context: ContextTypes.DEFAULT_TYPE):
    consumer_name = f"bot-{socket.gethostname()}"
    for message_id, event in STORE.read_events(consumer_name):
        try:
            if event.get("event") == "job_progress":
                job_id = event["job_id"]
                job = STORE.get_job(job_id) or {}
                await edit_progress_messages(
                    context,
                    job_id,
                    format_progress_message(job, event),
                )
            elif event.get("event") == "job_failed":
                job_id = event["job_id"]
                job = STORE.get_job(job_id) or {}
                text = (
                    f"{job.get('series_name', 'Anime')} could not be prepared.\n"
                    f"{job.get('error', 'Please retry later.')}"
                )
                progress_messages = STORE.get_progress_messages(job_id)
                for chat_id in STORE.take_failed_waiters(job_id):
                    message_id_to_edit = progress_messages.get(chat_id)
                    if message_id_to_edit:
                        try:
                            await context.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=message_id_to_edit,
                                text=text,
                            )
                        except BadRequest:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=text,
                            )
                    else:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=text,
                        )
                STORE.clear_progress_messages(job_id)
            STORE.acknowledge_event(message_id)
        except Exception:
            logger.exception("Could not process worker event %s", message_id)


def main():
    global SETTINGS, STORE
    SETTINGS = load_settings(require_bot=True)
    STORE = initialize_store(SETTINGS.redis_url)

    # Create application
    application = Application.builder().token(SETTINGS.bot_token).build()

    # Get job queue for scheduled tasks
    job_queue = application.job_queue
    job_queue.run_repeating(process_worker_events, interval=2, first=2)

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("getanime", getanime))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, debug_message))
    application.add_handler(
        MessageHandler(filters.VIDEO | filters.Document.VIDEO, check_document)
    )

    application.add_error_handler(error_handler)

    # Start the bot
    logger.info('Starting bot...')
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
