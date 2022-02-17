from cgitb import text
import logging
import json
from operator import truediv
from time import time
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from telegram.update import Update
from botUtils import showhelp,parse_search_query,getalltsfiles,getAnimelink
import subprocess
import datetime
import pytz



#enabling Logging
logging.basicConfig(format='%(levelname)s - %(asctime)s - %(name)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

with open('bot/config/botConfig.json', 'r') as config:
    configdata = json.load(config)

API_TOKEN = configdata.get("bot_token")


def start(update,context):
    update.message.reply_text("Thanks for using Araon Bot(v:0.01)\nThis is a alpha built so expect delayed response and many bugs\nIf you spot any issue feel free to reach out")


def help(update,context):
    text = showhelp()
    update.message.reply_text(text)
    

def search(update, context):
    logger.info('Search function is called!')
    link = getAnimelink(update.message.text)
    


def get(update, context):
    logger.info('download function is called!')
    chat_id = update.message.chat_id
    rawUserInput = update.message.text
    userInput = rawUserInput[:]
    if userInput and not userInput == " ":
        userdata = parse_search_query(userInput)
        update.message.reply_text(f"Checking Internal Db\nAnime: {userdata.get('series')}\nSeason: {userdata.get('season_id')}\nEpisode: {userdata.get('episode_id')}")
        download_status = subprocess.check_call("python downloaderService/main.py "+'"'+userdata.get('series')+'"'+' '+ userdata.get('episode_id') , shell=True)
    else:
        update.message.reply_text("Please refer to /help")
        
    update.message.reply_text(f"{userdata.get('series')} - {userdata.get('episode_id')} almost done downloading on the server side!")
    filepath = getalltsfiles()
    #update.message.reply_text(f"{userdata.get('series')} - {userdata.get('episode_id')} Uploading Started!")
    upload_status = subprocess.check_call("python uploaderService/main.py " +'"'+filepath+'"'+ ' ' + str(chat_id) + ' ' + (userdata.get('series')+str(userdata.get('episode_id'))), shell=True)

    
def error(update, context):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)
    update.message.reply_text("Something has went wrong!, Please retry :)")
    

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
        context.bot.send_video(end_user_chat_id,file_id,supports_streaming=True,timeout=120)

  

def debug_message(update, context):
    logger.info('debug_message function is called!')
    user_id = update.message.from_user.id
    #update.message.reply_text("Invalid command")

def callback_minute(context):
    context.bot.send_message(chat_id = configdata.get('agent_user_id'), text = 'Heart_beat <3')

# def check_for_update():
#     logger.info('Checking Update for Animdl')
#     subprocess.check_call("python -m pip install git+https://www.github.com/justfoolingaround/animdl")
    

def main():
    updater = Updater(token=API_TOKEN, use_context=True, request_kwargs={'read_timeout': 10, 'connect_timeout': 10})
    job = updater.job_queue
    # Get the dispatcher to register handlers
    dp = updater.dispatcher
    job.run_repeating(callback_minute, interval=120,first=10)
    
    # added handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(CommandHandler("search", search))
    dp.add_handler(CommandHandler("get", get))
    dp.add_handler(MessageHandler(Filters.text, debug_message))
    dp.add_handler(MessageHandler(Filters.video, check_document))

    dp.add_error_handler(error)

    updater.start_polling(timeout=120)
    updater.idle()



if __name__ == '__main__':
    main()