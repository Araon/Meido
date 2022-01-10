import logging
import json
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from telegram.update import Update
from botUtils import showhelp,parse_search_query


#enabling Logging
logging.basicConfig(format='%(levelname)s - %(asctime)s - %(name)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

with open('config/botConfig.json', 'r') as config:
    configdata = json.load(config)

API_TOKEN = configdata.get("bot_token")


def start(update,context):
    update.message.reply_text("Hello there!")


def help(update,context):
    text = showhelp()
    update.message.reply_text(text)

    
def search(update, context):
    logger.info('Search function is called!')
    
    update.message.reply_text('Searching....')

def get(update, context):
    logger.info('download function is called!')
    chat_id = update.message.chat_id
    rawUserInput = update.message.text
    userInput = rawUserInput[5:]
    if userInput and not userInput == " ":
        userdata = parse_search_query(userInput)
        update.message.reply_text(f"Checking Internal Db\nAnime: {userdata.get('series')}\nSeason: {userdata.get('season_id')}\nEpisode: {userdata.get('episode_id')}")
        
        
    else:
        update.message.reply_text("Please refer to /help")
    
def getall(update, context):
    logger.info('download function is called!')
    chat_id = update.message.chat_id
    rawUserInput = update.message.text
    userInput = rawUserInput[7:]
    if userInput and not userInput == " ":
        userdata = parse_search_query(userInput)
        update.message.reply_text(f"Checking Internal Db\nAnime: {userdata.get('series')}\nSeason: {userdata.get('season_id')}")
        
        
    else:
        update.message.reply_text("Please refer to /help")
    


def error(update, context):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def check_document(update, context):
    '''
    This function is important as this checks for all the files uploaded to the telegram server
    and returns a file id
    '''
    logger.info('check_document function is called!')
    user_id = update.message.from_user.id
    
    if user_id == configdata.get('agent_user_id'):
        file_id = update.message.video.file_id
        caption = update.message.caption  
        end_user_chat_id = caption.split(":")[0]
        #Keep in mind here i have to parse the chat_id from the caption above
        context.bot.send_video(end_user_chat_id,file_id,supports_streaming=True)

  

def debug_message(update, context):
    logger.info('debug_message function is called!')
    user_id = update.message.from_user.id
    
    update.message.reply_text(str(user_id))



    


def main():
    updater = Updater(token=API_TOKEN, use_context=True)
    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # on different commands - answer in Telegram
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(CommandHandler("search", search))
    dp.add_handler(CommandHandler("get", get))
    dp.add_handler(CommandHandler("getall", getall))
    
    
    dp.add_handler(MessageHandler(Filters.text, debug_message))
    dp.add_handler(MessageHandler(Filters.video, check_document))

    dp.add_error_handler(error)
    
    updater.start_polling()
    updater.idle()



if __name__ == '__main__':
    main()