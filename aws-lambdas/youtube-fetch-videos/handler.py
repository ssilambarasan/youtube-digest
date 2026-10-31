"""
Main Lambda handler for YouTube Subscriptions service.
"""
import json
from typing import Any, Dict
from datetime import datetime

from utils.helpers import get_logger, process_sqs_message, get_playlist_items, prepare_records_to_insert, db_interaction

logger = get_logger(__name__)

def FetchVideos(event: Dict[str, Any], context: Any):
    """
    Lambda handler that ingests an SQS record, fetches recent uploads, and persists metadata.

    The event is expected to contain a single SQS record with channel metadata in JSON format.
    The function fetches the latest uploads from the associated playlist and stores the
    resulting video metadata in PostgreSQL for downstream processing.
    """

    execution_id = context.aws_request_id
    logger.info(f"Starting Youtube Fetch Videos Module with execution id {execution_id}")

    try:
        logger.info(f"Received Event: {json.dumps(event)}")
        payload = process_sqs_message(event)
        logger.info(
            f"Processing channel {payload['channel_title']} ({payload['channel_id']}) from batch {payload['batch_id']}"
        )

        timestamp_str = payload.get("last_video_published_at")
        last_video_published_at = (datetime.fromisoformat(timestamp_str) if timestamp_str else None)

        logger.info(
            f"Starting to fetch all uploaded videos for {payload['channel_title']} playlist {payload['uploads_playlist_id']}"
        )

        allVideoDetails = get_playlist_items(payload['uploads_playlist_id'],last_video_published_at)

        if allVideoDetails:
            logger.info(
                f"{len(allVideoDetails)} new videos available since {last_video_published_at} for channel {payload['channel_title']}"
            )

            data_to_insert = prepare_records_to_insert(payload,allVideoDetails)
            db_interaction(data_to_insert,payload['batch_id'],payload['channel_title'])
            
        else:
            logger.info(
                f"No videos available to process since {last_video_published_at} for channel {payload['channel_title']}"
            )

        logger.info(
            f"Youtube Fetch Videos Module Completed Sucessfully for channel {payload['channel_title']}"
        )
    except Exception as e:
        logger.error(f"Error in Youtube Fetch Videos Module: {str(e)}", exc_info=True)
        raise