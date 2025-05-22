import os
import html
import logging
import asyncio
import threading
from waitress import serve
from jiosaavn import JioSaavn
from dotenv import load_dotenv
from flask import Flask, jsonify

app = Flask(__name__)
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)
PLAYLIST_URL = os.getenv("PLAYLIST_URL", "")
cached_songs = []
cached_new_releases = []


async def get_top_songs_from_playlist(playlist_url: str, limit: int = 12):
    saavn = JioSaavn()
    try:
        playlist_data = await saavn.get_playlist_songs(playlist_url, limit=limit)
        # logger.info(f"Raw playlist data: {playlist_data}")

        songs = []

        if isinstance(playlist_data, dict):
            data = playlist_data.get("data", {})
            if isinstance(data, dict):
                songs = data.get("list", [])
            else:
                logger.error("'data' is not a dictionary")
                return None
        else:
            logger.error("Unexpected data format: playlist_data is not a dict")
            return None

        for song in songs:
            if isinstance(song, dict):
                song["title"] = html.unescape(song.get("title", ""))
                song["subtitle"] = html.unescape(song.get("subtitle", ""))

            if "150x150" in song.get("image", ""):
                song["image"] = song["image"].replace("150x150", "500x500")

        return songs

    except Exception as e:
        logger.error(f"Error fetching playlist: {e}")
        return None


# 3 hrs = 10800
async def fetch_songs_periodically(interval: int = 7200):
    global cached_songs
    while True:
        logger.info("Fetching latest songs...")
        songs = await get_top_songs_from_playlist(PLAYLIST_URL)
        new_output = []

        if songs and isinstance(songs, list):
            for song in songs[:12]:
                new_output.append(
                    {
                        "id": song.get("id", ""),
                        "name": song.get("title", ""),
                        "primaryArtists": song.get("subtitle", ""),
                        "image": song.get("image", ""),
                        "downloadUrl": song.get("perma_url", ""),
                    }
                )
        cached_songs = new_output
        logger.info(f"Updated {len(cached_songs)} songs.")
        logger.info("Sleeping for 3 hours...")
        await asyncio.sleep(interval)


async def get_new_releases():
    try:
        saavn = JioSaavn()
        response = await saavn.get_new_releases()

        songs = response.get("data", [])
        if not isinstance(songs, list):
            logger.error(f"Expected list for 'data', but got {type(songs)}")
            return []

        output = []
        for song in songs[:12]:
            subtitle = song.get("subtitle") or ""

            if not subtitle:
                more_info = song.get("more_info") or {}
                artist_map = more_info.get("artistMap") or {}
                artists = artist_map.get("artists") or []
                subtitle = ", ".join(
                    [artist.get("name", "") for artist in artists if artist.get("name")]
                )

            output.append(
                {
                    "id": song.get("id", ""),
                    "name": html.unescape(song.get("title", "")),
                    "primaryArtists": html.unescape(subtitle),
                    "image": song.get("image", "").replace("150x150", "500x500"),
                    "downloadUrl": song.get("perma_url", ""),
                }
            )

        return output

    except Exception as e:
        logger.error(f"Error fetching new release: {e}")
        return []


async def fetch_new_releases_periodically(interval: int = 7200):
    global cached_new_releases
    while True:
        logger.info("Fetching new releases...")
        songs = await get_new_releases()

        if songs and isinstance(songs, list):
            cached_new_releases = songs

        logger.info(f"Updated {len(cached_new_releases)} new releases.")
        logger.info("Sleeping for 3 hours...")
        await asyncio.sleep(interval)


@app.route("/")
def index():
    return "Sanvia is running. Visit particular routes for songs."


@app.route("/songs")
def get_songs():
    return jsonify(cached_songs)


@app.route("/new-releases")
def new_releases():
    return jsonify(cached_new_releases)


def run_flask():
    serve(app, host="0.0.0.0", port=8000)


async def main():
    try:
        asyncio.create_task(fetch_songs_periodically())
        asyncio.create_task(fetch_new_releases_periodically())

        server_thread = threading.Thread(target=run_flask)
        server_thread.daemon = True
        server_thread.start()

        while True:
            await asyncio.sleep(3600)  # 3600
    except Exception as e:
        logger.error(f"Main loop exception: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    except KeyboardInterrupt:
        logger.info("Shutting down...")
