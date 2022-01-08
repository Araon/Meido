'''
Here are the following bot commands

/get - will download the anime episode you wanted
example - /get Death note, s1, ep3

/getadd - will provide all the episode of an anime in a given season
example - /getall Death Note, s1

/search - will provide deatails about an anime
example - /search Death Note

'''

def showhelp():
    helpText = "Here are the following bot commands\n\n/get - will download the anime episode you wanted\nexample - /get Death note, s1, ep3\n\n/getadd - will provide all the episode of an anime in a given season\nexample - /getall Death Note, s1\n\n/search - will provide deatails about an anime\nexample - /search Death Note"
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

