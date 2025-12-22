from dotenv import load_dotenv
import json
import logging
from auth.authentication import get_authenticated_service
from googleapiclient.errors import HttpError
from typing import List
from pathlib import Path

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SCOPED_SUBSCRIPTION_FILE = DATA_DIR / "scoped_subscriptions.json"
PAYLOAD_CONFIG_FILE = DATA_DIR / "payload_config.json"

def load_scoped_subscriptions() -> List[dict]:

    try:
        # Fetching all channels from scoped subscribtions
        logger.info("Fetching channel subscription details")

        with open(SCOPED_SUBSCRIPTION_FILE,'r',encoding='utf-8') as f:
            subs = json.load(f)
        
        if not subs:
            raise ValueError("No subscriptions found in the scoped subscriptions file")
        
        logger.info(f"Loaded {len(subs)} subscription(s)")
        return subs

    except Exception as e:
        logger.exception("Error loading scoped subscription channels")
        raise

def get_uploads_playlist_id(youtube, channelId:str) -> str:
    """
    List all channels the authenticated user is subscribed to.
    """  
    try:
        request = youtube.channels().list(
            id=channelId,
            part='snippet,contentDetails'
        )
        response = request.execute()

        totalResults = response["pageInfo"]["totalResults"]

        if totalResults != 1:
            raise ValueError(f"Expected 1 result, but got {totalResults}")

        uploadsPlaylistId = response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        return uploadsPlaylistId

    except HttpError:
        logger.exception("HTTP error fetching uploads playlist")
        raise

def write_payloadconfig_to_file(config: List[dict]) -> None:
    # Optionally save to a JSON file
    logger.info("Writing the payload configuration to a file on data folder")

    try:
        with open(PAYLOAD_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        logger.info("Payload configurations successfully saved to data folder")
    except Exception as e:
        logger.exception("Failed to write payload configuration to file")
        raise

if __name__ == '__main__':

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    load_dotenv(override=True)

    try:
        channels = load_scoped_subscriptions()

        logger.info(f"Processing {len(channels)} channel(s) to get the channel's upload playlist id")

        # Invoking authentication to Youtube Data API
        youtube = get_authenticated_service()

        for channel in channels:
            channel_id = channel.get("channel_id")
            channel_title = channel.get("channel_title")

            if not channel_id or not channel_title:
                logger.warning(f"Skipping invalid entry: {channel}")
            else:
                # Fetch the Uploads Playlist ID for a channel.
                logger.info(f"Trying to fetch the uploads playlist id for the channel: {channel_title}")

                uploadsPlaylistId = get_uploads_playlist_id(youtube, channel_id)
                channel["uploadsPlaylistId"] = uploadsPlaylistId

        logger.info(f"Enriched {len(channels)} channel(s) with playlist IDs")
        write_payloadconfig_to_file(channels)
    except Exception as e:
        logger.exception("Error in preparig payload with uploads playlist id workflow")