"""
Main Lambda handler for YouTube Subscriptions service.
"""
import json
from typing import Any, Dict

from utils.helpers import (
    get_authenticated_service,
    get_logger,
    list_subscriptions,
    write_files_to_s3,
)
logger = get_logger(__name__)

def FetchAllSubscriptions(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Process YouTube subscription events.

    Fetches the authenticated user's YouTube subscriptions and writes them to S3.

    Args:
        event: Lambda event data
        context: Lambda context object

    Returns:
        HTTP response dict with statusCode and body
    """
    try:
        logger.info(f"Processing event: {json.dumps(event)}")

        youtube = get_authenticated_service()
        subscriptions = list_subscriptions(youtube)
        write_files_to_s3(subscriptions)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Subscriptions fetched and written to S3 successfully"
            })
        }

    except Exception as e:
        logger.error(f"Error processing subscriptions: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }

