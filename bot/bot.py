#!/usr/bin/env python3


import logging
import json
from datetime import datetime
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters
)
from botUtils import (
    showhelp, parse_search_query, getalltsfiles
)
from database import getData, postData, updateData
import subprocess

BOT_VERSION = 0.1

# enabling Logging
logging.basicConfig(
    format='%(levelname)s - %(asctime)s - %(name)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# fetching config file
try:
    with open('bot/config/botConfig.json', 'r') as config:
        configdata = json.load(config)
except Exception:
    raise Exception('CONFIG FILE NOT FOUND!')

API_TOKEN = configdata.get("bot_token")


def start(update, context):
    message = (
        f"Thanks for using Araon Bot({BOT_VERSION})\n"
        "This is a alpha built so expect delayed response and many bugs\n"
        "If you spot any issue feel free to reach out"
    )
    update.message.reply_text(message)


def help(update, context):
    text = showhelp()
    update.message.reply_text(text)


def getanime(update, context):
    '''
    Fetches the anime file on the mongo db and then if not found,
    downloads the anime using animeld
    '''
    logger.info('download function is called!')

    chat_id = update.message.chat_id
    rawUserInput = update.message.text
    userInput = rawUserInput[10:]

    if userInput and not userInput == " ":
        userdata = parse_search_query(userInput)

        reply_msg = (
            f"Checking Internal Db\n"
            f"Anime: {userdata.get('series_name')}\n"
            f"Season: {userdata.get('season_id')}\n"
            f"Episode: {userdata.get('episode_id')}"
        )
        update.message.reply_text(reply_msg)
        logger.info('search_in_mongodb:"%s"', userdata)

        search_in_mongodb = {
            "series_name": userdata.get('series_name'),
            "season_id": userdata.get('season_id'),
            "episode_id": userdata.get('episode_id')
        }
        anime_name = getData(search_in_mongodb)
        if anime_name:
            logger.info('Got data from mongoDB')
            logger.info(anime_name)
            updateData(anime_name)
            try:
                if anime_name.get("file_id"):
                    context.bot.send_video(
                        chat_id,
                        anime_name.get("file_id"),
                        supports_streaming=True,
                        timeout=120
                    )
                    return  # Exit early since we found and sent the video
                else:
                    msg = "Anime found in database but file_id is missing"
                    update.message.reply_text(msg)
            except Exception as e:
                logger.error(f"Error sending video: {e}")
                update.message.reply_text("Error sending video. Please retry.")
                return

        # Only download and upload if anime not found in database
        logger.info('Anime not found in database, downloading...')
        series_name = userdata.get('series_name')
        episode_id = userdata.get('episode_id')
        cmd = (
            f"python downloaderService/main.py "
            f'"{series_name}" {episode_id}'
        )
        subprocess.check_call(cmd, shell=True)
        reply_msg = f"{series_name} - {episode_id} is done downloading!"
        update.message.reply_text(reply_msg)
        filepath = getalltsfiles()
        if filepath:
            object_id = f"{series_name}-{episode_id}"
            upload_cmd = (
                f"python uploaderService/main.py "
                f'"{filepath}" {chat_id} {object_id}'
            )
            subprocess.check_call(upload_cmd, shell=True)
        else:
            update.message.reply_text("Error: Could not find downloaded file")

    else:
        update.message.reply_text("Please refer to /help")


def error(update, context):
    """Log Errors caused by Updates."""
    logger.warning(
        'Update "%s" caused error "%s" and "%s"',
        update, context.error, context
    )
    update.message.reply_text("Something has went wrong!, Please retry")


def check_document(update, context):
    '''
    This function is important as this checks for all the files uploaded
    to the telegram server and returns a file id
    '''
    logger.info('check_document function is called!')
    user_id = update.message.from_user.id

    if user_id == configdata.get('agent_user_id'):
        file_id = update.message.video.file_id
        caption = update.message.caption
        object_id = caption.split(":")[1]
        end_user_chat_id = caption.split(":")[0]
        series_name = object_id.split("-")[0]
        episode_id = object_id.split("-")[1]

        data2post = {
            "series_name": series_name,
            "episode_id": episode_id,
            "file_id": file_id,
            "times_queried": 0,
            "date_added": datetime.now()
        }
        logger.info('Got Posting data to mongoDB')
        logger.info(data2post)
        postData(data2post)

        # Keep in mind here i have to parse the chat_id from caption above
        context.bot.send_video(
            end_user_chat_id,
            file_id,
            supports_streaming=True,
            timeout=120
        )


def debug_message(update, context):
    logger.info('debug_message function is called!')
    # update.message.reply_text("Invalid command")


def callback_minute(context):
    agent_id = configdata.get('agent_user_id')
    context.bot.send_message(chat_id=agent_id, text='Heart_beat <3')


# def check_for_update():
#     logger.info('Checking Update for Animdl')
#     subprocess.check_call(
#         "python -m pip install "
#         "git+https://www.github.com/justfoolingaround/animdl"
#     )


def main():
    request_kwargs = {
        'read_timeout': 10,
        'connect_timeout': 10
    }
    updater = Updater(
        token=API_TOKEN,
        use_context=True,
        request_kwargs=request_kwargs
    )
    job = updater.job_queue

    # Get the dispatcher to register handlers
    dp = updater.dispatcher
    job.run_repeating(callback_minute, interval=120, first=10)

    # added handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(CommandHandler("getanime", getanime))
    dp.add_handler(MessageHandler(Filters.text, debug_message))
    dp.add_handler(MessageHandler(Filters.video, check_document))

    dp.add_error_handler(error)

    updater.start_polling(timeout=120)
    updater.idle()


if __name__ == '__main__':
    main()
