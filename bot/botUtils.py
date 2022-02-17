'''
Here are the following bot commands

/get - will download the anime episode you wanted
example - /get Death note, s1, ep3

/search - will provide deatails about an anime
example - /search Death Note

'''
import os
import subprocess
import re 
def showhelp():
    helpText = "Here are the following bot commands\n\n/get - will download the anime episode you wanted(make sure you seperate the name and the season and ep with comma)\nexample - /get Death note, 1, 3\n\n/search(still in development) - will provide deatails about an anime\nexample - /search Death Note"
    return helpText

def parse_search_query(raw_input):
    text = raw_input.split(',')
    series_name = text[0]
    try:
        season_id = ''.join([n for n in text[1] if n.isdigit()])
    except:
        season_id = -1
    try:
        episode_id = ''.join([n for n in text[2] if n.isdigit()])
    except:
        episode_id = -1
        
    query_obj = {
        "series" : series_name,
        "season_id" : season_id,
        "episode_id": episode_id
    }
    return query_obj

def getalltsfiles():
    walk_dir = '.'
    for root, _, files in os.walk(walk_dir):
        for file in files:
            if (file.split(".")[-1].lower() == 'mp4'):
                mp4FilePath = os.path.join(root, os.path.splitext(file)[0] + ".mp4")
                # seriously mate, i'm tired and this might be the worst piece of hack i've done in my life
                # yet!
                mp4FilePath = mp4FilePath.replace("\\","/")
                return mp4FilePath
            

def getAnimelink(search_query):
    userInput = search_query[8:]
    if userInput and not userInput == " ":
        userdata = parse_search_query(userInput)

        import pdb
        pdb.set_trace()
        #return raw_search_data


# python uploaderService/main.py ./Naruto/E04.mp4 5023977571 naruto4

