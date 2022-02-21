from pymongo import MongoClient

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
        return 0
        
def getData(data):
    anime_data = col.find_one(filter=data) #{"serise_name":"anime_name", "episode_id":2 }
    return anime_data
    
def updateData(data):
    try:
        update_id = col.update_one({"series_name":data.get('series_name') , "episode_id": data.get('episode_id')},{'$inc': {'times_queried':1}})
        return update_id
    except:
        return 0

#result = db.test.update_one({'x': 1}, {'$inc': {'x': 3}})