"""
Main Lambda handler for YouTube Subscriptions service.
"""
import json
import os
import boto3
from typing import Any, Dict
from datetime import datetime

from utils.helpers import (
    get_logger,
    db_interaction
)

logger = get_logger(__name__)

def PayloadGenerator(event: Dict[str, Any], context: Any):
    """
    Lambda handler to generate and forward payload data to SQS.
    
    Fetches scoped channel subscriptions from PostgreSQL database, constructs
    payload messages containing channel metadata and uploads playlist IDs,
    and sends them to an SQS queue for downstream processing.
    """
    try:
        logger.info(f"Processing event: {json.dumps(event)}")
        logger.info("Starting Youtube channels enrichment")

        scoped_subscriptions = db_interaction()

        sqs_url = os.getenv("SQS_QUEUE_URL")

        if not sqs_url:
            raise ValueError("SQS_QUEUE_URL environment variable not set")

        sqs_client = boto3.client("sqs")
        batch_id = datetime.now().strftime('%m%d%Y%H%M%S')

        for eachChannel in scoped_subscriptions:
            payload = {
                "batch_id": batch_id,
                "channel_id": eachChannel[0],
                "channel_title": eachChannel[1],
                "uploads_playlist_id": eachChannel[2],
                "last_video_published_at": (eachChannel[3].isoformat() if eachChannel[3] else None)
            }

            sqs_client.send_message(
                QueueUrl=sqs_url,
                MessageBody=json.dumps(payload)
            )

            logger.info(f"Sent message for channel: {eachChannel[1]}")

        logger.info("Youtube channels enrichment completed successfully")

    except Exception as e:
        logger.error(f"Error enriching youtube channel upload playlists: {str(e)}", exc_info=True)