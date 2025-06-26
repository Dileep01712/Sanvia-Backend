import os
import html
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
PLAYLIST_URL = os.getenv("PLAYLIST_URL")

if not firebase_admin._apps:
    cred = credentials.Certificate("firebase_credentials.json")
    firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL})


async def upload_now_trending_to_firebase(
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
    ref = db.reference(firebase_node)
    return ref.get()
