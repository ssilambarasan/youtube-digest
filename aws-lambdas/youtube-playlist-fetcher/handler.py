"""
Main Lambda handler for YouTube Subscriptions service.
"""
import json
from typing import Any, Dict

from utils.helpers import (
    get_authenticated_service,
    get_logger,
    load_scoped_subscriptions,
    enrich_upload_playlistid,
    db_interaction
)

logger = get_logger(__name__)

def FetchPlaylistId(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler to enrich YouTube channels with their uploads playlist IDs.
    
    Loads scoped channel subscriptions from a JSON file, authenticates with the YouTube API,
    fetches the uploads playlist ID for each channel, and returns a success/error response.
    """
    try:
        logger.info(f"Processing event: {json.dumps(event)}")
        logger.info("Starting Youtube channels enrichment")

        channels = load_scoped_subscriptions()
        logger.info(f"Processing {len(channels)} channel(s) to get the channel's upload playlist id")

        youtube = get_authenticated_service()
        enriched_channels = enrich_upload_playlistid(youtube,channels)
        db_interaction(enriched_channels)

        logger.info("Youtube channels enrichment completed successfully")

    except Exception as e:
        logger.error(f"Error enriching youtube channel upload playlists: {str(e)}", exc_info=True)