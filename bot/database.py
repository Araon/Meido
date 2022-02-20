from pymongo import MongoClient
import datetime
import json
from botUtils import parse_search_query

client = MongoClient('mongodb://localhost:27017/')

#database
db = client["animeDatabase"]
#collection
col = db["animeDatabase"]


'''
 * DB Models
    * animeDatabase
         - id *Primary Key*
         - series_name <string>
         - season_id <int>
         - episode_id <int>
         - file_id <string>
         - times_queried <int>
         - date_added <date>
'''

def postData(data):
    try:
        post_id = col.insert_one(data).inserted_id
        return post_id
    except:
        return {}
        
def getData(data):
    anime_data = col.find_one(filter=data)
    return anime_data
    
