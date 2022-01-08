# Requirements

 * Send anime to user
 * downaload anime from website and upload to telegram
 * provide data related to animes

# Data Model

 * DB Models
    * seriesName
         - id *Primary Key*
         - Series_name
         - Season_id
         - Episode_id

# Happy Path
* /get and /getll
    1. call a function videoFetcher(user_input).
    2. the videoFetcher will check in mapping db if found return file_id
    3. if the not found in mapping db will call downloadVideoService and it will return file_path,file_name,duration
    4. then uploadVideoService will take the file_path as input return file_id after uploading
    5. the file_id will be then returned

# Expansion

 * Send anime directly to user who has subscribed to them
 * Pre-download animes that are popular
 * watched list
 * recomendation