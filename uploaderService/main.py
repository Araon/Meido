#!/usr/bin/env python3
#https://sudonull.com/post/62683-Telegram-bots-Uploading-files-larger-than-50mb

'''
fun facts i just came accross

the .send_file() function will have to send the file to the bot that will be serving the user,
Just uploading the file to the server via upload , getting file_id and passing it to the bot will not work,
file_id only works inside the chat in which it was created.
So that our bot can send the file to the user by file_id 
the agent must send the bot this file
then the bot will receive own file_id for this file and will be able to dispose of it.

'''

from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeVideo
import asyncio
import json


with open('config/agentConfig.json', 'r') as config:
    configdata = json.load(config)

entity = configdata.get('entity') #session name - it doesn't matter what
api_id = configdata.get('api_id')
api_hash = configdata.get('api_hash')
phone =  configdata.get('phone')

bot_name = configdata.get('bot_name')


# if not client.is_user_authorized():
#     #client.send_code_request(phone) #at the first start - uncomment, after authorization to avoid FloodWait I advise you to comment
#     client.sign_in(phone, input('Enter code: '))


def callback(current, total):
    # for upload progression
    print('Uploaded: {:.2%}'.format(current / total))


'''
bot_name = the actual bot name
file_path = where the file is downloaded
chat_id = this is the end user chat_id, sent over caption to bot, so it can parse and send it to the correct user
object_id = an internal id used for mapping of file_id and filename stored in the server(for optimization).
'''
async def uploadVideo(bot_name,file_path,chat_id,object_id):
    async with TelegramClient(entity, api_id, api_hash) as client:
        await client.send_file(
                            str(bot_name),
                            file_path,
                            caption=str(chat_id + ':' + object_id),
                            attributes=[DocumentAttributeVideo(0,0,0)],
                            progress_callback=callback,
                            part_size_kb=512,
                            supports_streaming=True,
                            )
        await client.disconnect()
    return 0

async def main(argv):
    file_path = argv[1]
    chat_id = argv[2]
    object_id = argv[3]
    
    await uploadVideo(bot_name,file_path,chat_id,object_id)


if __name__ == '__main__':
    import sys
    asyncio.run(main(sys.argv[0:]))
    
# python uploader.py rainfall.mp4 rainfall chat_id narutos1ep34