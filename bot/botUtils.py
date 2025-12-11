'''
Here are the following bot commands

/get - will download the anime episode you wanted
example - /get Death note, s1, ep3

/search - will provide deatails about an anime
example - /search Death Note

'''
import os
import re
from pathlib import Path

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent


def showhelp():
    helpText = "Here are the following bot commands\n \
    \n/getanime - will download the anime episode you wanted(make sure you seperate the name and the season and ep with comma) \
    \nexample - /getanime Death note, 1, 3\n\n/search(still in development) \
    - will provide deatails about an anime\nexample - /search Death Note"
    return helpText

def normalize_series_name(series_name):
    """
    Normalize series name to create a consistent series_key.

    The returned key is safe for filesystem paths and for object_id parsing
    (series_key-s{season_id}-e{episode_id}) because it contains only lowercase
    letters, digits, and underscores.
    """
    if not series_name:
        return ""
    normalized = series_name.lower().strip()
    # Replace any run of non-alphanumeric characters with underscore
    normalized = re.sub(r'[^a-z0-9]+', '_', normalized)
    # Trim leading/trailing underscores
    normalized = normalized.strip('_')
    return normalized

def parse_search_query(raw_input):
    text = raw_input.split(',')
    series_name = text[0].strip() if len(text) > 0 else ""
    try:
        season_id = ''.join([n for n in text[1] if n.isdigit()]) if len(text) > 1 else "-1"
        season_id = int(season_id) if season_id else -1
    except (IndexError, ValueError):
        season_id = -1
    try:
        episode_id = ''.join([n for n in text[2] if n.isdigit()]) if len(text) > 2 else "-1"
        episode_id = int(episode_id) if episode_id else -1
    except (IndexError, ValueError):
        episode_id = -1

    query_obj = {
        "series_name" : series_name,
        "season_id" : season_id,
        "episode_id": episode_id
    }
    return query_obj

def get_download_path(series_key, season_id, episode_id):
    """
    Get deterministic download path for an anime episode.
    Returns Path object for the download directory and mp4 file.
    """
    # Format: downloads/<series_key>/S<season_id>E<episode_id>/
    season_str = f"S{season_id:02d}" if season_id >= 0 else "S00"
    episode_str = f"E{episode_id:02d}" if episode_id >= 0 else "E00"
    download_dir = PROJECT_ROOT / "downloads" / series_key / f"{season_str}{episode_str}"
    mp4_file = download_dir / "episode.mp4"
    return download_dir, mp4_file

def getalltsfiles(series_key=None, season_id=None, episode_id=None):
    """
    Get the mp4 file path. If parameters are provided, use deterministic path.
    Otherwise, fall back to scanning (for backward compatibility during transition).
    """
    if series_key and season_id is not None and episode_id is not None:
        # Use deterministic path
        _, mp4_file = get_download_path(series_key, season_id, episode_id)
        if mp4_file.exists():
            return str(mp4_file)
        return None
    
    # Fallback: Find .mp4 files in the project directory (legacy behavior)
    walk_dir = PROJECT_ROOT
    for root, _, files in os.walk(walk_dir):
        for file in files:
            if file.split(".")[-1].lower() == 'mp4':
                mp4FilePath = os.path.join(root, file)
                # Normalize path separators
                mp4FilePath = os.path.normpath(mp4FilePath)
                return mp4FilePath
    return None


# python uploaderService/main.py ./Naruto/E04.mp4 5023977571 naruto4
