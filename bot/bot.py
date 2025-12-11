#!/usr/bin/env python3

import logging
import json
import sys
import os
from pathlib import Path
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)
from botUtils import (
    showhelp, parse_search_query, getalltsfiles, normalize_series_name, get_download_path
)
from database import getData, postData, updateData
import subprocess

BOT_VERSION = 0.1

# Get the project root directory (parent of bot directory)
_project_root_override = os.getenv("MEIDO_PROJECT_ROOT") or os.getenv("TEST_PROJECT_ROOT")
PROJECT_ROOT = (
    Path(_project_root_override).expanduser().resolve()
    if _project_root_override
    else Path(__file__).parent.parent
)

# enabling Logging
logging.basicConfig(
    format='%(levelname)s - %(asctime)s - %(name)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# fetching config file
config_path = PROJECT_ROOT / 'bot' / 'config' / 'botConfig.json'
try:
    with open(config_path, 'r') as config:
        configdata = json.load(config)
except FileNotFoundError:
    logger.error(f'Config file not found at {config_path}')
    raise Exception('CONFIG FILE NOT FOUND!')
except json.JSONDecodeError as e:
    logger.error(f'Invalid JSON in config file: {e}')
    raise Exception('INVALID CONFIG FILE!')

API_TOKEN = configdata.get("bot_token")
if not API_TOKEN:
    raise Exception('bot_token not found in config file!')


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
    '''
    Fetches the anime file on the mongo db and then if not found,
    downloads the anime using animdl
    '''
    logger.info('download function is called!')

    chat_id = update.effective_chat.id
    rawUserInput = update.message.text
    userInput = rawUserInput[10:] if len(rawUserInput) > 10 else ""

    if userInput and not userInput == " ":
        userdata = parse_search_query(userInput)
        
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
        logger.info('search_in_mongodb:"%s"', userdata)

        # Use series_key for database queries
        search_in_mongodb = {
            "series_key": series_key,
            "season_id": season_id,
            "episode_id": episode_id
        }
        anime_name = getData(search_in_mongodb)
        if anime_name:
            logger.info('Got data from mongoDB')
            logger.info(anime_name)
            updateData(anime_name)
            try:
                if anime_name.get("file_id"):
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=anime_name.get("file_id"),
                        supports_streaming=True,
                        read_timeout=120,
                        write_timeout=120
                    )
                    return  # Exit early since we found and sent the video
                else:
                    msg = "Anime found in database but file_id is missing"
                    await update.message.reply_text(msg)
            except Exception as e:
                logger.error(f"Error sending video: {e}")
                logger.info("Cache miss - file_id failed, falling back to re-download")
                await update.message.reply_text("Error sending cached video. Re-downloading...")
                # Fall through to download logic

        # Only download and upload if anime not found in database or cache failed
        logger.info('Anime not found in database, downloading...')
        
        # Get deterministic download path
        download_dir, expected_mp4 = get_download_path(series_key, season_id, episode_id)
        download_dir.mkdir(parents=True, exist_ok=True)

        # Use absolute path for downloader service
        downloader_script = PROJECT_ROOT / 'downloaderService' / 'main.py'
        cmd = [
            sys.executable,
            str(downloader_script),
            series_name,
            str(season_id),
            str(episode_id),
            str(download_dir)
        ]
        
        try:
            subprocess.check_call(cmd, cwd=str(PROJECT_ROOT))
            reply_msg = f"{series_name} - S{season_id}E{episode_id} is done downloading!"
            await update.message.reply_text(reply_msg)

            # Use deterministic path instead of scanning
            filepath = getalltsfiles(series_key, season_id, episode_id)
            if filepath and os.path.exists(filepath):
                # Create object_id with season: series_key-s{season_id}-e{episode_id}
                object_id = f"{series_key}-s{season_id}-e{episode_id}"
                uploader_script = PROJECT_ROOT / 'uploaderService' / 'main.py'
                upload_cmd = [
                    sys.executable,
                    str(uploader_script),
                    filepath,
                    str(chat_id),
                    object_id
                ]
                try:
                    subprocess.check_call(upload_cmd, cwd=str(PROJECT_ROOT))
                    # Cleanup: Delete the local mp4 file after successful upload
                    # (Telegram file_id is now cached, so local file is no longer needed)
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        logger.info(f'Cleaned up local file: {filepath}')
                except subprocess.CalledProcessError as upload_error:
                    logger.error(f"Upload failed: {upload_error}")
                    # Keep the file for potential retry
                    raise
            else:
                await update.message.reply_text("Error: Could not find downloaded file")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error in subprocess call: {e}")
            await update.message.reply_text("Error during download/upload process. Please retry.")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            await update.message.reply_text("An unexpected error occurred. Please retry.")

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

    if user_id == configdata.get('agent_user_id'):
        if not update.message.video:
            logger.warning('Received message without video')
            return

        file_id = update.message.video.file_id
        caption = update.message.caption

        if not caption or ':' not in caption:
            logger.warning('Received video without proper caption format')
            return

        try:
            parts = caption.split(":")
            if len(parts) < 2:
                logger.error(f'Invalid caption format: {caption}')
                return

            end_user_chat_id = parts[0]
            object_id = parts[1]

            # Parse object_id format: series_key-s{season_id}-e{episode_id}
            # Example: "death_note-s1-e3"
            try:
                # Split by '-' and look for 's' and 'e' prefixes
                parts_obj = object_id.split("-")
                if len(parts_obj) < 3:
                    logger.error(f'Invalid object_id format: {object_id}')
                    return
                
                series_key = parts_obj[0]
                season_part = None
                episode_part = None
                
                for part in parts_obj[1:]:
                    if part.startswith('s') and part[1:].isdigit():
                        season_part = part
                    elif part.startswith('e') and part[1:].isdigit():
                        episode_part = part
                
                if not season_part or not episode_part:
                    logger.error(f'Invalid object_id format (missing s/e): {object_id}')
                    return
                
                season_id = int(season_part[1:])
                episode_id = int(episode_part[1:])
                
                # Try to get original series_name from database if exists, otherwise use series_key
                existing = getData({"series_key": series_key, "season_id": season_id, "episode_id": episode_id})
                series_name = existing.get("series_name") if existing and existing.get("series_name") else series_key.replace("_", " ").title()
                
            except (ValueError, IndexError) as e:
                logger.error(f'Error parsing object_id: {object_id}, error: {e}')
                return

            data2post = {
                "series_key": series_key,
                "series_name": series_name,
                "season_id": season_id,
                "episode_id": episode_id,
                "file_id": file_id,
                "times_queried": 0,
                "date_added": datetime.now()
            }
            logger.info('Got Posting data to mongoDB')
            logger.info(data2post)
            postData(data2post)

            # Keep in mind here i have to parse the chat_id from caption above
            await context.bot.send_video(
                chat_id=int(end_user_chat_id),
                video=file_id,
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120
            )
        except ValueError as e:
            logger.error(f'Error parsing caption or chat_id: {e}')
        except Exception as e:
            logger.error(f'Error in check_document: {e}')


async def debug_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info('debug_message function is called!')


async def callback_minute(context: ContextTypes.DEFAULT_TYPE):
    agent_id = configdata.get('agent_user_id')
    if agent_id:
        try:
            await context.bot.send_message(chat_id=agent_id, text='Heart_beat <3')
        except Exception as e:
            logger.error(f'Error sending heartbeat: {e}')


def main():
    # Create application
    application = Application.builder().token(API_TOKEN).build()

    # Get job queue for scheduled tasks
    job_queue = application.job_queue
    job_queue.run_repeating(callback_minute, interval=120, first=10)

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("getanime", getanime))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, debug_message))
    application.add_handler(MessageHandler(filters.VIDEO, check_document))

    application.add_error_handler(error_handler)

    # Start the bot
    logger.info('Starting bot...')
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
