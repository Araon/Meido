from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
import os
import logging

logger = logging.getLogger(__name__)

# Get MongoDB URL from environment variable or use default
MONGO_DB_URL = os.getenv('MONGO_DB_URL', 'mongodb://localhost:27017/')

try:
    client = MongoClient(MONGO_DB_URL, serverSelectionTimeoutMS=5000)
    # Test connection
    client.admin.command('ping')
    logger.info('Successfully connected to MongoDB')
except (ConnectionFailure, ServerSelectionTimeoutError) as e:
    logger.error(f'Failed to connect to MongoDB: {e}')
    raise

#database
db = client["animeDatabase"]
#collection
col = db["animeDatabase"]

'''
 * DB Models
    * animeDatabase
         - id *Primary Key*
         - series_key <string> (normalized series name)
         - series_name <string> (original series name)
         - season_id <int>
         - episode_id <int>
         - file_id <string>
         - times_queried <int>
         - date_added <date>
'''

def create_indexes():
    """Create unique compound index on (series_key, season_id, episode_id)"""
    try:
        col.create_index(
            [("series_key", 1), ("season_id", 1), ("episode_id", 1)],
            unique=True,
            name="series_season_episode_unique"
        )
        logger.info('Created unique index on (series_key, season_id, episode_id)')
    except Exception as e:
        # Index might already exist, which is fine
        logger.debug(f'Index creation note: {e}')

# Create indexes on module load
create_indexes()

def postData(data):
    """Insert data into the database"""
    try:
        post_id = col.insert_one(data).inserted_id
        logger.info(f'Inserted document with id: {post_id}')
        return post_id
    except Exception as e:
        logger.error(f'Error inserting data: {e}')
        return None


def getData(data):
    """Query data from the database"""
    try:
        anime_data = col.find_one(filter=data)  # {"series_key":"anime_key", "season_id":1, "episode_id":2 }
        return anime_data
    except Exception as e:
        logger.error(f'Error querying data: {e}')
        return None


def updateData(data):
    """Update the times_queried field for a document"""
    try:
        # Build query with all key fields
        query = {}
        if 'series_key' in data:
            query['series_key'] = data.get('series_key')
        elif 'series_name' in data:
            # Fallback for backward compatibility
            query['series_name'] = data.get('series_name')
        
        if 'season_id' in data:
            query['season_id'] = data.get('season_id')
        if 'episode_id' in data:
            query['episode_id'] = data.get('episode_id')
        
        update_result = col.update_one(
            query,
            {'$inc': {'times_queried': 1}}
        )
        if update_result.matched_count > 0:
            logger.info(f'Updated document: {query}')
        return update_result
    except Exception as e:
        logger.error(f'Error updating data: {e}')
        return None

#result = db.test.update_one({'x': 1}, {'$inc': {'x': 3}})
