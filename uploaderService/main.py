#!/usr/bin/env python3

# https://sudonull.com/post/62683-Telegram-bots-Uploading-files-larger-than-50mb

'''
fun facts i just came accross

the .send_file() function will have to send the file to the bot that
will be serving the user, Just uploading the file to the server via
upload, getting file_id and passing it to the bot will not work,
file_id only works inside the chat in which it was created.
So that our bot can send the file to the user by file_id
the agent must send the bot this file
then the bot will receive own file_id for this file and will be able
to dispose of it.

'''
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeVideo
import asyncio
import json
import logging
from pathlib import Path

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# basic logging
logging.basicConfig(
    format='%(levelname)s - %(asctime)s - %(name)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# Load config file
config_path = PROJECT_ROOT / 'uploaderService' / 'config' / 'agentConfig.json'
try:
    with open(config_path, 'r') as config:
        configdata = json.load(config)
except FileNotFoundError:
    logger.error(f'Config file not found at {config_path}')
    raise Exception('CONFIG FILE NOT FOUND!')
except json.JSONDecodeError as e:
    logger.error(f'Invalid JSON in config file: {e}')
    raise Exception('INVALID CONFIG FILE!')

entity = configdata.get('entity')  # session name - it doesn't matter what
api_id_raw = configdata.get('api_id')
api_hash = configdata.get('api_hash')
phone = configdata.get('phone')
bot_name = configdata.get('bot_name')

# Coerce api_id to int (Telethon expects an integer)
try:
    api_id = int(api_id_raw) if api_id_raw is not None else None
except (TypeError, ValueError):
    api_id = None

# Validate required fields
if not all([entity, api_id, api_hash, phone, bot_name]):
    missing = [k for k, v in {
        'entity': entity,
        'api_id': api_id,
        'api_hash': api_hash,
        'phone': phone,
        'bot_name': bot_name
    }.items() if not v]
    raise Exception(f'Missing required config fields: {", ".join(missing)}')


async def callback(current, total):
    # for upload progression
    if total > 0:
        logger.info('Uploaded: {:.2%}'.format(current / total))


'''
bot_name = the actual bot name
file_path = where the file is downloaded
chat_id = this is the end user chat_id, sent over caption to bot,
            so it can parse and send it to the correct user
object_id = an internal id used for mapping of file_id
            and filename stored in the server(for optimization).
'''


async def uploadVideo(bot_name, file_path, chat_id, object_id):
    logger.info('video uploading initiated')
    
    # Resolve file path
    file_path = Path(file_path)
    if not file_path.is_absolute():
        file_path = PROJECT_ROOT / file_path
    
    if not file_path.exists():
        raise FileNotFoundError(f'File not found: {file_path}')
    
    # Session file path
    session_path = PROJECT_ROOT / f'{entity}.session'
    
    async with TelegramClient(str(session_path), api_id, api_hash) as client:
        if not await client.is_user_authorized():
            # await client.send_code_request(phone)
            # at the first start - uncomment, after authorization to avoid
            # FloodWait I advise you to comment
            code = input('Enter code: ')
            await client.sign_in(phone, code)
        
        await client.send_file(
            str(bot_name),
            str(file_path),
            caption=str(chat_id) + ':' + str(object_id),
            attributes=[DocumentAttributeVideo(0, 0, 0)],
            progress_callback=callback,
            part_size_kb=512,
            supports_streaming=True,
        )
        await client.disconnect()
    return 0


async def main(argv):
    if len(argv) < 4:
        raise ValueError('Usage: python main.py <file_path> <chat_id> <object_id>')
    
    file_path = argv[1]
    chat_id = argv[2]
    object_id = argv[3]

    await uploadVideo(bot_name, file_path, chat_id, object_id)


if __name__ == '__main__':
    import sys
    try:
        asyncio.run(main(sys.argv))
    except KeyboardInterrupt:
        logger.info('Interrupted by user')
    except Exception as e:
        logger.error(f'Error: {e}')
        sys.exit(1)

# python uploaderService/main.py <file_path> <chat_id> <object_id>
