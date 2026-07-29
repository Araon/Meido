#!/usr/bin/env python3

import logging
import sys
import socket
from pathlib import Path

# Support both `python -m bot.bot` and direct script execution.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from telegram import BotCommand, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from meido_settings import load_settings
from bot.commands import (
    showhelp,
    parse_search_query,
    normalize_series_name,
    validate_search_query,
)
from bot.store import initialize_store
from bot.ui import (
    confirmation_keyboard,
    episode_keyboard,
    failed_job_keyboard,
    home_keyboard,
    job_cancel_keyboard,
    navigation_keyboard,
    ready_keyboard,
    season_keyboard,
    status_keyboard,
)

BOT_VERSION = 0.1
SETTINGS = None
STORE = None
TITLE, SEASON, EPISODE, CONFIRM = range(4)

HOME_TEXT = (
    "Welcome to Meido.\n\n"
    "Choose an action below. You can request an episode with buttons "
    "or use the quick command:\n"
    "/getanime Death Note, 1, 3"
)

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
                reply_markup=job_cancel_keyboard(job_id),
            )
        except BadRequest as error:
            if "message is not modified" not in str(error).lower():
                logger.warning(
                    "Could not edit progress message for job %s: %s",
                    job_id,
                    error,
                )


async def render_card(update, text, reply_markup=None):
    """Reply to a command or update an inline-menu message in place."""
    query = update.callback_query
    if query:
        await query.answer()
        try:
            await query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
            )
        except BadRequest as error:
            if "message is not modified" not in str(error).lower():
                raise
        return query.message
    return await update.effective_message.reply_text(
        text,
        reply_markup=reply_markup,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        HOME_TEXT,
        reply_markup=home_keyboard(),
    )


async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await render_card(update, HOME_TEXT, home_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await render_card(update, showhelp(), home_keyboard())


def request_data(context):
    return context.user_data.setdefault("anime_request", {})


async def prompt_for_title(update):
    return await render_card(
        update,
        "What anime do you want?\n\n"
        "Send the title as a message, for example: Fairy Tail",
        navigation_keyboard(),
    )


async def getanime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the guided flow or process the legacy one-line shortcut."""
    context.user_data.pop("anime_request", None)
    raw_user_input = (
        update.effective_message.text
        if update.callback_query is None
        else ""
    ) or ""
    user_input = raw_user_input.partition(" ")[2].strip()
    if user_input:
        data = parse_search_query(user_input)
        validation_error = validate_search_query(data)
        if validation_error:
            await update.effective_message.reply_text(
                f"{validation_error}\n\n"
                "Use: /getanime <name>, <season>, <episode>\n"
                "Or send /getanime without arguments for the guided flow.",
                reply_markup=home_keyboard(),
            )
            return ConversationHandler.END
        await enqueue_request(update, context, data)
        return ConversationHandler.END

    context.user_data["anime_request"] = {}
    await prompt_for_title(update)
    return TITLE


async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = (update.effective_message.text or "").strip()
    if not title or not normalize_series_name(title):
        await update.effective_message.reply_text(
            "Please send a title containing letters or numbers."
        )
        return TITLE
    if len(title) > 200:
        await update.effective_message.reply_text(
            "That title is too long. Please keep it under 200 characters."
        )
        return TITLE

    request_data(context)["series_name"] = title
    await update.effective_message.reply_text(
        f"{title}\n\nChoose a season or type its number.",
        reply_markup=season_keyboard(),
    )
    return SEASON


async def back_to_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["anime_request"] = {}
    await prompt_for_title(update)
    return TITLE


def positive_number(value):
    value = str(value).strip()
    return int(value) if value.isdigit() and int(value) > 0 else None


async def receive_season(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query and query.data == "season:custom":
        await render_card(
            update,
            "Send the season number as a message.",
            navigation_keyboard(back_callback="request:back:title"),
        )
        return SEASON

    value = query.data.partition(":")[2] if query else update.message.text
    season = positive_number(value)
    if season is None:
        await update.effective_message.reply_text(
            "Season must be a positive whole number."
        )
        return SEASON

    data = request_data(context)
    data["season_id"] = season
    title = data.get("series_name", "Anime")
    text = (
        f"{title} • Season {season}\n\n"
        "Choose an episode or type its number."
    )
    if query:
        await render_card(update, text, episode_keyboard())
    else:
        await update.effective_message.reply_text(
            text,
            reply_markup=episode_keyboard(),
        )
    return EPISODE


async def back_to_season(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = request_data(context)
    data.pop("season_id", None)
    data.pop("episode_id", None)
    await render_card(
        update,
        f"{data.get('series_name', 'Anime')}\n\n"
        "Choose a season or type its number.",
        season_keyboard(),
    )
    return SEASON


async def change_episode_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    start = positive_number(update.callback_query.data.partition(":")[2]) or 1
    data = request_data(context)
    await render_card(
        update,
        f"{data.get('series_name', 'Anime')} • "
        f"Season {data.get('season_id', 1)}\n\n"
        f"Choose an episode ({start}–{start + 11}).",
        episode_keyboard(start),
    )
    return EPISODE


async def receive_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query and query.data == "episode:custom":
        await render_card(
            update,
            "Send the episode number as a message.",
            navigation_keyboard(back_callback="request:back:season"),
        )
        return EPISODE

    value = query.data.partition(":")[2] if query else update.message.text
    episode = positive_number(value)
    if episode is None:
        await update.effective_message.reply_text(
            "Episode must be a positive whole number."
        )
        return EPISODE

    data = request_data(context)
    data["episode_id"] = episode
    text = (
        "Confirm your request\n\n"
        f"{data['series_name']}\n"
        f"Season {data['season_id']} • Episode {episode}"
    )
    if query:
        await render_card(update, text, confirmation_keyboard())
    else:
        await update.effective_message.reply_text(
            text,
            reply_markup=confirmation_keyboard(),
        )
    return CONFIRM


async def confirm_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = dict(request_data(context))
    validation_error = validate_search_query(data)
    if validation_error:
        await render_card(
            update,
            f"{validation_error}\nPlease start the request again.",
            home_keyboard(),
        )
        context.user_data.pop("anime_request", None)
        return ConversationHandler.END
    await enqueue_request(update, context, data)
    context.user_data.pop("anime_request", None)
    return ConversationHandler.END


async def cancel_request_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.pop("anime_request", None)
    await render_card(
        update,
        "Request cancelled. Nothing was queued.",
        home_keyboard(),
    )
    return ConversationHandler.END


async def expired_request_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.pop("anime_request", None)
    await render_card(
        update,
        "This request menu expired. Start a new one when you are ready.",
        home_keyboard(),
    )


async def enqueue_request(update, context, data):
    chat_id = update.effective_chat.id
    series_name = data["series_name"]
    season_id = int(data["season_id"])
    episode_id = int(data["episode_id"])
    series_key = normalize_series_name(series_name)
    logger.info("episode_request=%s", data)

    cached = STORE.get_episode(series_key, season_id, episode_id)
    if cached and cached.get("file_id"):
        try:
            await context.bot.send_video(
                chat_id=chat_id,
                video=cached["file_id"],
                caption=(
                    f"{series_name} • S{season_id:02d}E{episode_id:02d}"
                ),
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
            )
            STORE.increment_episode_queries(
                series_key,
                season_id,
                episode_id,
            )
            await render_card(
                update,
                f"Ready from cache\n\n"
                f"{series_name} • S{season_id:02d}E{episode_id:02d}",
                ready_keyboard(),
            )
            return
        except Exception:
            logger.exception("Cached file failed; queuing a replacement")

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
                "Queued\n\n"
                f"{series_name} • S{season_id:02d}E{episode_id:02d}\n"
                "Waiting for a download slot.\n"
                f"Job: {job_id[:8]}"
            )
        else:
            message = (
                "Already in progress\n\n"
                f"{series_name} • S{season_id:02d}E{episode_id:02d}\n"
                "You joined the existing request.\n"
                f"Job: {job_id[:8]}"
            )
        progress_message = await render_card(
            update,
            message,
            job_cancel_keyboard(job_id),
        )
        STORE.set_progress_message(
            job_id,
            chat_id,
            progress_message.message_id,
        )
    except Exception:
        logger.exception("Could not enqueue episode")
        await render_card(
            update,
            "The media queue is unavailable. Please retry shortly.",
            home_keyboard(),
        )


def job_status_label(job):
    phase = job.get("phase") or job.get("status") or "queued"
    label = PHASE_LABELS.get(
        phase,
        str(phase).replace("_", " ").title(),
    )
    progress = int(job.get("progress_percent") or 0)
    return (
        f"• {job['series_name']} "
        f"S{int(job['season_id']):02d}E{int(job['episode_id']):02d}\n"
        f"  {label} • {progress}% • {job['job_id'][:8]}"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jobs = STORE.get_active_jobs(update.effective_chat.id)
    if jobs:
        text = (
            "Active requests\n\n"
            + "\n\n".join(job_status_label(job) for job in jobs[:5])
        )
        if len(jobs) > 5:
            text += f"\n\n…and {len(jobs) - 5} more."
    else:
        text = "No active requests.\n\nReady to find something?"
    await render_card(update, text, status_keyboard(jobs))


async def cancel_job_updates(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    job_id = update.callback_query.data.rpartition(":")[2]
    chat_id = update.effective_chat.id
    removed = STORE.remove_waiter(job_id, chat_id)
    STORE.remove_progress_message(job_id, chat_id)
    if removed:
        text = (
            "Updates stopped for this request.\n\n"
            "A shared download may continue in the background and become "
            "available from cache later."
        )
    else:
        text = "This request is no longer active for this chat."
    await render_card(update, text, home_keyboard())


async def retry_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    job_id = update.callback_query.data.rpartition(":")[2]
    job = STORE.get_job(job_id)
    if not job:
        await render_card(
            update,
            "That request has expired. Please create it again.",
            home_keyboard(),
        )
        return
    await enqueue_request(
        update,
        context,
        {
            "series_name": job["series_name"],
            "season_id": int(job["season_id"]),
            "episode_id": int(job["episode_id"]),
        },
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log Errors caused by Updates."""
    logger.error(
        'Update "%s" caused error "%s"',
        update, context.error
    )
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text(
                "Something went wrong. Please retry.",
                reply_markup=home_keyboard(),
            )
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
                "Ready\n\n"
                f"{job.get('series_name', 'Anime')} • "
                f"S{int(job.get('season_id', 0)):02d}"
                f"E{int(job.get('episode_id', 0)):02d}"
            )
            for chat_id, message_id in progress_messages.items():
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=ready_text,
                        reply_markup=ready_keyboard(),
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
    await update.message.reply_text(
        "Use the menu to start a request, or send /getanime for the "
        "guided flow.",
        reply_markup=home_keyboard(),
    )


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
                    "Could not prepare this episode\n\n"
                    f"{job.get('series_name', 'Anime')}\n"
                    f"{job.get('error', 'Please retry later.')}"
                )
                retry_markup = failed_job_keyboard(job_id)
                progress_messages = STORE.get_progress_messages(job_id)
                for chat_id in STORE.take_failed_waiters(job_id):
                    message_id_to_edit = progress_messages.get(chat_id)
                    if message_id_to_edit:
                        try:
                            await context.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=message_id_to_edit,
                                text=text,
                                reply_markup=retry_markup,
                            )
                        except BadRequest:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=text,
                                reply_markup=retry_markup,
                            )
                    else:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=text,
                            reply_markup=retry_markup,
                        )
                STORE.clear_progress_messages(job_id)
            STORE.acknowledge_event(message_id)
        except Exception:
            logger.exception("Could not process worker event %s", message_id)


async def configure_commands(application):
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Open the Meido home menu"),
            BotCommand("anime", "Find an episode with guided buttons"),
            BotCommand("getanime", "Request an episode"),
            BotCommand("status", "Show active requests"),
            BotCommand("help", "Show help and shortcuts"),
            BotCommand("cancel", "Exit the current request flow"),
        ]
    )


def build_conversation_handler():
    return ConversationHandler(
        entry_points=[
            CommandHandler(["getanime", "anime"], getanime),
            CallbackQueryHandler(
                getanime,
                pattern=r"^menu:getanime$",
            ),
        ],
        states={
            TITLE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_title,
                ),
            ],
            SEASON: [
                CallbackQueryHandler(
                    receive_season,
                    pattern=r"^season:(?:[1-9]\d*|custom)$",
                ),
                CallbackQueryHandler(
                    back_to_title,
                    pattern=r"^request:back:title$",
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_season,
                ),
            ],
            EPISODE: [
                CallbackQueryHandler(
                    receive_episode,
                    pattern=r"^episode:(?:[1-9]\d*|custom)$",
                ),
                CallbackQueryHandler(
                    change_episode_page,
                    pattern=r"^episode_page:[1-9]\d*$",
                ),
                CallbackQueryHandler(
                    back_to_season,
                    pattern=r"^request:back:season$",
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_episode,
                ),
            ],
            CONFIRM: [
                CallbackQueryHandler(
                    confirm_request,
                    pattern=r"^request:confirm$",
                ),
                CallbackQueryHandler(
                    back_to_title,
                    pattern=r"^request:back:title$",
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_request_flow),
            CallbackQueryHandler(
                cancel_request_flow,
                pattern=r"^(?:request:cancel|menu:home)$",
            ),
        ],
        allow_reentry=True,
        conversation_timeout=10 * 60,
    )


def main():
    global SETTINGS, STORE
    SETTINGS = load_settings(require_bot=True)
    STORE = initialize_store(SETTINGS.redis_url)

    # Create application
    application = (
        Application.builder()
        .token(SETTINGS.bot_token)
        .post_init(configure_commands)
        .build()
    )

    # Get job queue for scheduled tasks
    job_queue = application.job_queue
    job_queue.run_repeating(process_worker_events, interval=2, first=2)

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_home))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(build_conversation_handler())
    application.add_handler(CommandHandler("cancel", show_home))
    application.add_handler(
        CallbackQueryHandler(
            show_home,
            pattern=r"^menu:home$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            help_command,
            pattern=r"^menu:help$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            status_command,
            pattern=r"^menu:status$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            cancel_job_updates,
            pattern=r"^job:cancel:[0-9a-f]{32}$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            retry_job,
            pattern=r"^job:retry:[0-9a-f]{32}$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            expired_request_flow,
            pattern=r"^request:",
        )
    )
    application.add_handler(
        MessageHandler(filters.VIDEO | filters.Document.VIDEO, check_document)
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            debug_message,
        )
    )

    application.add_error_handler(error_handler)

    # Start the bot
    logger.info('Starting bot...')
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
