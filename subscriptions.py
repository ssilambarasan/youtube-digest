import json
import logging
from typing import List
from pathlib import Path
from dotenv import load_dotenv
from auth.authentication import get_authenticated_service

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SUBSCRIPTION_FILE = DATA_DIR / "subscriptions.json"

def list_subscriptions(youtube) -> List[dict]:
    """
    List all channels the authenticated user is subscribed to.
    """
    logger.info("Starting to fetch all my youtube channel subscriptions")

    subscriptions = []
    next_page_token = None
    
    try:
        while True:
            # Request subscriptions
            request = youtube.subscriptions().list(
                part='snippet,contentDetails',
                mine=True,
                maxResults=50,  # Max allowed per request
                pageToken=next_page_token
            )
            response = request.execute()
            
            # Process each subscription
            for item in response.get('items', []):
                subscription_info = {
                    'channel_id': item['snippet']['resourceId']['channelId'],
                    'channel_title': item['snippet']['title'],
                    'description': item['snippet']['description'],
                    'published_at': item['snippet']['publishedAt']
                }

                subscriptions.append(subscription_info)
            
            # Check if there are more pages to process
            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break
       
        logger.info(f"Total subscriptions: {len(subscriptions)}")
        logger.info("Completed fetching all youtube channel subscriptions")
        return subscriptions
    
    except Exception as e:
        logger.exception("Error fetching subscriptions")
        raise

def write_subscriptions_to_file(subscriptions: List[dict]) -> None:
    # Optionally save to a JSON file
    logger.info("Writing the youtube subscriptions to a file on data folder")

    try:
        with open(SUBSCRIPTION_FILE, 'w', encoding='utf-8') as f:
            json.dump(subscriptions, f, indent=2, ensure_ascii=False)

        logger.info("Subscriptions successfully saved to data folder")
    except Exception as e:
        logger.exception("Failed to write subscriptions to file")
        raise

if __name__ == '__main__':

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    load_dotenv(override=True)

    try:
        # Invoking authentication to Youtube Data API
        youtube = get_authenticated_service()

        # Fetching all channels that we subscribed to
        subscriptions = list_subscriptions(youtube)

        # Writing the subscriptions to a file
        write_subscriptions_to_file(subscriptions)

    except Exception as e:
        logger.exception("Error in subscriptions workflow")