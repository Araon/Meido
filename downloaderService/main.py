#!/usr/bin/env python3

import subprocess
import os
import sys
from pathlib import Path

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent


def downloadVideo(search_query, search_query_range, download_dir):
    # animdl download "demon slayer" -r 1
    # Run animdl in the target download directory so files are created there
    cmd = [
        'animdl',
        'download',
        search_query,
        '-r',
        str(search_query_range),
        '--auto',
    ]
    print(*cmd)
    subprocess.run(cmd, cwd=str(download_dir), check=True)


def getalltsfiles(download_dir):
    """Find .ts files in the download directory and return tuple of (ts_file, mp4_file) paths"""
    download_path = Path(download_dir)
    if not download_path.exists():
        return None, None
    
    # Look for .ts files in the download directory (and immediate subdirectories)
    for root, _, files in os.walk(download_path):
        for file in files:
            if file.split(".")[-1].lower() == 'ts':
                filePath = os.path.join(root, file)
                mp4FilePath = os.path.join(root, os.path.splitext(file)[0] + ".mp4")
                if os.path.isfile(mp4FilePath):
                    continue
                return filePath, mp4FilePath
    return None, None


def convert2mp4(infile, outfile):
    # ffmpeg -i E01.ts -c:v copy -c:a copy -preset:v ultrafast
    # -segment_list_flags +live video.mp4
    if not os.path.exists(infile):
        raise FileNotFoundError(f'Input file not found: {infile}')
    
    subprocess.run([
        'ffmpeg', '-i', infile, '-c:v', 'copy', '-c:a', 'copy',
        '-preset:v', 'ultrafast', '-segment_list_flags', '+live', outfile
    ], cwd=str(PROJECT_ROOT), check=True)


def main(argv):
    if len(argv) < 5:
        print('Usage: python main.py <search_query> <season_id> <episode_range> <download_dir>')
        sys.exit(1)
    
    search_query = argv[1]
    season_id = argv[2]  # Now accepting season_id
    search_query_range = argv[3]
    download_dir = Path(argv[4])
    
    # Ensure download directory exists
    download_dir.mkdir(parents=True, exist_ok=True)
    
    print(f'Downloading: {search_query}, Season: {season_id}, Episode: {search_query_range}')
    
    try:
        downloadVideo(search_query, search_query_range, download_dir)
        infile, outfile = getalltsfiles(download_dir)
        
        if infile and outfile:
            convert2mp4(infile, outfile)
            # Clean up .ts file after conversion
            if os.path.exists(infile):
                os.remove(infile)
        else:
            print('Warning: No .ts files found to convert')
    except subprocess.CalledProcessError as e:
        print(f'Error in subprocess: {e}')
        sys.exit(1)
    except Exception as e:
        print(f'Error: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main(sys.argv)
