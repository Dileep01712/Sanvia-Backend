import os
import re
import html
import logging
import asyncio
import requests
import threading
from waitress import serve
from flask_cors import CORS
from jiosaavn import JioSaavn
from dotenv import load_dotenv
from asyncio import AbstractEventLoop
from flask import Flask, jsonify, send_file, request
from firebase import (
    upload_now_trending_songs_to_firebase,
    read_now_trending_from_firebase,
    upload_random_albums_to_firebase,
    read_random_albums_from_firebase,
)

app = Flask(__name__)
CORS(app)
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

main_event_loop: AbstractEventLoop | None = None

saavn = JioSaavn()
cached_top_artists: list = []
cached_new_releases: list = []

PLAYLIST_URL = os.getenv("PLAYLIST_URL", "")
OUTPUT_FILE = "now_trending.json"


async def fetch_and_save_now_trending_songs_periodically(interval: int = 7200):
    while True:
        logger.info(
            "Background: fetching and uploading now trending songs to Firebase..."
        )

        try:
            await upload_now_trending_songs_to_firebase()
            logger.info("Background: successfully uploaded now trending songs.")
        except Exception as e:
            logger.error(f"Error fetching playlist: {e}")

        logger.info(f"Sleeping for 2 hours...")
        await asyncio.sleep(interval)


async def get_new_releases():
    try:
        response = await saavn.get_new_releases()

        songs = response.get("data", [])
        if not isinstance(songs, list):
            logger.error(f"Expected list for 'data', but got {type(songs)}")
            return []

        result = []
        for song in songs[:12]:
            subtitle = song.get("subtitle") or ""
            if not subtitle:
                more_info = song.get("more_info") or {}
                artist_map = more_info.get("artistMap") or {}
                artists = artist_map.get("artists") or []
                subtitle = ", ".join(
                    [artist.get("name", "") for artist in artists if artist.get("name")]
                )

            result.append(
                {
                    "id": song.get("id", ""),
                    "name": html.unescape(song.get("title", "")),
                    "primaryArtists": html.unescape(subtitle),
                    "image": song.get("image", "").replace("150x150", "500x500"),
                    "downloadUrl": song.get("perma_url", ""),
                }
            )

        return result

    except Exception as e:
        logger.error(f"Error fetching new release: {e}")
        return []


async def fetch_new_releases_periodically(interval: int = 7200):
    global cached_new_releases
    while True:
        logger.info("Background: fetching and updating new releases from JioSaavn…")

        songs = await get_new_releases()
        if songs:
            cached_new_releases = songs
            logger.info(f"Background: updated {len(cached_new_releases)} new releases.")
        else:
            logger.warning("Background: got no new releases.")

        logger.info(f"Sleeping for 2 hours...")
        await asyncio.sleep(interval)


async def fetch_and_save_random_albums_periodically(interval: int = 7200):
    while True:
        logger.info("Background: fetching and uploading random albums to Firebase...")

        try:
            await upload_random_albums_to_firebase()
            logger.info("Background: successfully uploaded random albums.")
        except Exception as e:
            logger.error(f"Background: failed to upload random albums - {e}")

        logger.info(f"Sleeping for 2 hours...")
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

        result = []
        for artist in artist_list[:limit]:
            result.append(
                {
                    "id": artist.get("artistid", ""),
                    "name": artist.get("name", ""),
                    "follower_count": artist.get("follower_count", ""),
                    "image": artist.get("image", "").replace("150x150", "500x500"),
                    "url": artist.get("perma_url", ""),
                }
            )

        return result

    except Exception as e:
        logging.error(f"Error fetching top artists: {e}")
        return []


async def fetch_top_artists_periodically(interval: int = 7200):
    global cached_top_artists
    while True:
        logger.info("Background: fetching and updating top artists from JioSaavn…")

        artists = await get_top_artists()
        if artists:
            cached_top_artists = artists
            logger.info(f"Background: updated {len(cached_top_artists)} top artists.")
        else:
            logger.warning("Background: got no top artists.")

        logger.info(f"Sleeping for 2 hours...")
        await asyncio.sleep(interval)


def sanitize_filename(name: str) -> str:
    """
    Remove invalid characters from file name for Windows.
    """
    return re.sub(r'[<>:"/\\|?*]', "", name).strip()


def download_audio(
    streaming_url: str, song_title: str, save_dir: str = "downloads"
) -> str:
    """
    Download audio from streaming URL and save locally.

    Args:
        streaming_url (str): Direct streaming URL of the song.
        song_title (str): Desired filename (will be sanitized).
        save_dir (str): Directory to save the file.

    Returns:
        str: Path to the downloaded file.
    """
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    sanitized_name = sanitize_filename(song_title) or "audio"
    file_path = os.path.join(save_dir, f"{sanitized_name}.mp3")

    try:
        resp = requests.get(streaming_url, stream=True)
        resp.raise_for_status()

        with open(file_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"Downloaded to {file_path}")
        return file_path
    except Exception as e:
        logger.error(f"Failed to download: {e}")
        return ""


@app.route("/")
def index():
    return "Sanvia-Backend is running. Visit particular routes for songs, albums and top artists."


@app.route("/now-trending")
def now_trending():
    logger.info("Serving /now-trending from Firebase")
    try:
        data = asyncio.run(read_now_trending_from_firebase())
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error reading now trending songs from firebase: {e}")
        return jsonify([]), 500


@app.route("/new-releases")
def new_releases():
    logger.info("Serving /new-releases from cache")
    return jsonify(cached_new_releases or [])


@app.route("/albums")
def get_albums():
    logger.info("Serving /albums from Firebase")
    try:
        data = asyncio.run(read_random_albums_from_firebase())
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error reading random albums from firebase: {e}")
        return jsonify([]), 500


@app.route("/top-artists")
def top_artists():
    logger.info("Serving /top-artists from cache")
    return jsonify(cached_top_artists or [])


@app.route("/download-song", methods=["POST"])
def download_song():
    data = request.get_json() or {}
    url = data.get("streamingUrl")
    title = data.get("title")

    if not url or not title:
        return jsonify({"error": "Missing parameters"}), 400

    path = download_audio(url, title)
    if path:
        return send_file(path, as_attachment=True)
    return jsonify({"error": "Download failed"}), 500


def run_flask():
    serve(app, host="0.0.0.0", port=8000)


async def main():
    try:
        global main_event_loop
        main_event_loop = asyncio.get_running_loop()

        asyncio.create_task(fetch_and_save_now_trending_songs_periodically())
        asyncio.create_task(fetch_and_save_random_albums_periodically())
        asyncio.create_task(fetch_new_releases_periodically())
        asyncio.create_task(fetch_top_artists_periodically())

        server_thread = threading.Thread(target=run_flask, daemon=True)
        server_thread.start()

        while True:
            await asyncio.sleep(3600)

    except Exception as e:
        logger.error(f"Main loop exception failed: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down…")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
