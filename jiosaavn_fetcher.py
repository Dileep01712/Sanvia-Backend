import os
import html
import string
import random
import logging
import asyncio
import threading
from waitress import serve
from jiosaavn import JioSaavn
from dotenv import load_dotenv
from flask import Flask, jsonify
from firebase import upload_now_trending_to_firebase, read_now_trending_from_firebase

app = Flask(__name__)
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)
PLAYLIST_URL = os.getenv("PLAYLIST_URL", "")
OUTPUT_FILE = "now_trending.json"
saavn = JioSaavn()
cached_albums = []
cached_top_artists = []
cached_new_releases = []


async def fetch_and_save_top_songs(limit: int = 12):
    try:
        await upload_now_trending_to_firebase(limit)
    except Exception as e:
        logger.error(f"Error fetching playlist: {e}")
        return


async def get_new_releases():
    try:
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


async def get_random_albums(limit=12):
    try:
        # 1) fire 7 single-letter queries
        letters = random.sample(string.ascii_lowercase, 7)
        pool = []
        for q in letters:
            resp = await saavn.search_albums(q)
            data = resp.get("data", []) if isinstance(resp, dict) else resp or []
            pool.extend(data)

        # 2) dedupe
        unique = {album["id"]: album for album in pool}.values()
        choices = list(unique)
        if not choices:
            return []

        picked = random.sample(choices, min(limit, len(choices)))
        result = []

        for album in picked:
            result.append(
                {
                    "id": album.get("id", ""),
                    "name": html.unescape(album.get("title", "")),
                    "primaryArtists": html.unescape(album.get("music", "")),
                    "image": album.get("image", "").replace("50x50", "500x500"),
                    "perma_url": album.get("url", ""),
                }
            )

        return result

    except Exception as e:
        logger.error(f"Error fetching random albums: {e}")
        return []


async def fetch_random_albums_periodically(interval: int = 7200):
    global cached_albums
    while True:
        logger.info("Fetching random albums...")
        albums = await get_random_albums()

        if albums:
            cached_albums = albums
            logger.info(f"Updated {len(albums)} random albums.")
        else:
            logger.warning("Failed to update album list.")

        logger.info("Sleeping for 3 hours...")
        await asyncio.sleep(interval)


async def get_top_artists(limit: int = 12):
    try:
        response = await saavn.get_top_artists()

        if not response or "data" not in response:
            logger.error(f"Failed to fetch playlist.")
            return

        data = response.get("data", {})

        if isinstance(data, dict):
            artist_list = data.get("top_artists", [])
        else:
            logger.error("'data' is not a dictionary")
            return

        top_artists = []
        for artist in artist_list[:limit]:
            top_artists.append(
                {
                    "id": artist.get("artistid", ""),
                    "name": artist.get("name", ""),
                    "follower_count": artist.get("follower_count", ""),
                    "image": artist.get("image", "").replace("150x150", "500x500"),
                    "url": artist.get("perma_url", ""),
                }
            )

        return top_artists

    except Exception as e:
        logging.error(f"Error fetching top artists: {e}")


async def fetch_top_artists_periodically(interval: int = 7200):
    global cached_top_artists
    while True:
        logger.info("Fetching top artists...")
        songs = await get_top_artists()

        if songs and isinstance(songs, list):
            cached_top_artists = songs

        logger.info(f"Updated {len(cached_top_artists)} top artists.")
        logger.info("Sleeping for 3 hours...")
        await asyncio.sleep(interval)


@app.route("/")
def index():
    return "Sanvia is running. Visit particular routes for songs."


@app.route("/now-trending")
def now_trending():
    try:
        data = asyncio.run(read_now_trending_from_firebase())
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error reading now trending from Firebase: {e}")
        return jsonify({"error": "Failed to fetch data"})


@app.route("/new-releases")
def new_releases():
    return jsonify(cached_new_releases)


@app.route("/albums")
def get_albums():
    return jsonify(cached_albums)


@app.route("/top-artists")
def top_artists():
    return jsonify(cached_top_artists)


def run_flask():
    serve(app, host="0.0.0.0", port=8000)


async def main():
    try:
        await fetch_and_save_top_songs()
        asyncio.create_task(fetch_new_releases_periodically())
        asyncio.create_task(fetch_random_albums_periodically())
        asyncio.create_task(fetch_top_artists_periodically())

        server_thread = threading.Thread(target=run_flask)
        server_thread.daemon = True
        server_thread.start()

        while True:
            await asyncio.sleep(3600)

    except Exception as e:
        logger.error(f"Main loop exception: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    except KeyboardInterrupt:
        logger.info("Shutting down...")
