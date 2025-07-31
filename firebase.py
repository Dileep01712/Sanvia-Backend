import os
import re
import json
import html
import string
import random
import asyncio
import logging
import firebase_admin
from jiosaavn import JioSaavn
from dotenv import load_dotenv
from firebase_admin import credentials, db


load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)

saavn = JioSaavn()
FIREBASE_DB_URL = os.getenv("FIREBASE_DB_URL")
FIREBASE_CREDENTIALS_JSON = json.loads(os.environ["FIREBASE_CREDENTIALS_JSON"])
PLAYLIST_URL = os.getenv("PLAYLIST_URL")

if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CREDENTIALS_JSON)
    firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})


async def upload_now_trending_songs_to_firebase(
    limit: int = 12, firebase_node: str = "/now_trending"
):
    try:
        playlist_data = await saavn.get_playlist_songs(PLAYLIST_URL, limit=limit)

        if not playlist_data or "data" not in playlist_data:
            logger.error("Failed to fetch playlist data.")
            return

        data = playlist_data.get("data", {})
        if not isinstance(data, dict):
            logger.error("'data' is not a dictionary.")
            return

        song_list = data.get("list", [])
        if not song_list:
            logger.warning("Playlist is empty.")
            return

        top_songs = []
        for song in song_list[:limit]:
            top_songs.append(
                {
                    "id": song.get("id", ""),
                    "name": html.unescape(song.get("title", "")),
                    "primaryArtists": html.unescape(song.get("subtitle", "")),
                    "image": song.get("image", "").replace("150x150", "500x500"),
                    "downloadUrl": song.get("perma_url", ""),
                }
            )

        db.reference(firebase_node).set(top_songs)
        logger.info(f"Uploaded {len(top_songs)} songs to Firebase at {firebase_node}")

    except Exception as e:
        logger.error(f"Error uploading songs to Firebase: {e}")


async def read_now_trending_from_firebase(firebase_node: str = "/now_trending"):
    try:
        ref = db.reference(firebase_node)
        songs = ref.get()

        if not songs:
            logger.warning("No songs found or data is not a list.")
            return []
        
        return songs

    except Exception as e:
        logger.error(f"Error reading songs from Firebase: {e}")
        return []


async def upload_random_albums_to_firebase(firebase_node: str = "/random_albums"):
    try:
        letters = list(string.ascii_uppercase)
        random.shuffle(letters)
        sample_letters = letters[:12]

        combined_results = []
        for letter in sample_letters:
            search_result = await saavn.search_albums(letter)
            await asyncio.sleep(2)
            if "data" in search_result:
                combined_results.extend(search_result["data"])

        unique_albums = {}
        for album in combined_results:
            unique_albums[album["id"]] = album

        final_album_list = []
        for album in unique_albums.values():
            final_album_list.append(
                {
                    "id": album.get("id", ""),
                    "name": html.unescape(album.get("title", "")),
                    "primaryArtists": html.unescape(album.get("music", "")),
                    "image": re.sub(r"\d+x\d+", "500x500", album.get("image", "")),
                    "downloadUrl": album.get("url", ""),
                }
            )

        if not final_album_list:
            logger.warning("Album list is empty after formatting.")
            return

        db.reference(firebase_node).set(final_album_list)
        logger.info(
            f"Uploaded {len(final_album_list)} albums to Firebase at {firebase_node}"
        )

    except Exception as e:
        logger.error(f"Error uploading albums to Firebase: {e}")


async def read_random_albums_from_firebase(
    limit: int = 12, firebase_node: str = "/random_albums"
):
    try:
        ref = db.reference(firebase_node)
        albums = ref.get()

        if not albums or not isinstance(albums, list):
            logger.warning("No albums found or data is not a list.")
            return []

        return random.sample(albums, min(limit, len(albums)))

    except Exception as e:
        logger.error(f"Error reading albums from Firebase: {e}")
        return []
