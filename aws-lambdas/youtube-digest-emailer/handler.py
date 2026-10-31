"""Main Lambda handler for the YouTube Digest Emailer service."""
import json
from typing import Any, Dict
from utils.helpers import get_logger, db_interaction, build_email_html, send_email

logger = get_logger(__name__)

def DigestEmailer(event: Dict[str, Any], context: Any):
    """Entry point for generating and emailing the daily YouTube digest."""

    execution_id = context.aws_request_id
    logger.info(f"Starting Youtube Daily Digest Module with execution id {execution_id}")

    try:
        logger.info(f"Received Event: {json.dumps(event)}")

        db_content = db_interaction()

        if db_content:
            c_batch_id, html_content = build_email_html(db_content)

            subject = f"Daily Youtube Digest - {c_batch_id}"
            send_email(subject,html_content)

        logger.info("Youtube Daily Digest Module completed successfully")
    except Exception as e:
        logger.error(
            f"Error while running Youtube Daily Digest Emailer Module: {str(e)}",
            exc_info=True,
        )
        raise