import logging
import json
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from telegram.update import Update

#enabling Logging

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

with open('config/botConfig.json', 'r') as config:
    configdata = json.load(config)

API_TOKEN = configdata.get("bot_token")

def start(update):
    """Send a message when the command /start is issued."""
    update.message.reply_text('Hi!')


def help(update):
    """Send a message when the command /help is issued."""
    update.message.reply_text('Help!')


def echo(update, context):
    """Echo the user message."""
    update.message.reply_text((update.message.text).upper())
    
def search(update, context):
    logger.info('Search function is called!')
    update.message.reply_text('Searching....')

def download(update, context):
    logger.info('download function is called!')
    update.message.reply_text('Downloading!')


def error(update, context):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def main():

    updater = Updater(token=API_TOKEN, use_context=True)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # on different commands - answer in Telegram
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(CommandHandler("search", search))
    dp.add_handler(CommandHandler("download", download))

    dp.add_handler(MessageHandler(Filters.text, echo))

    dp.add_error_handler(error)
    
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()