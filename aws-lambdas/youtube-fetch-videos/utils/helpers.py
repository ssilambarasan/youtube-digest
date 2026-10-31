"""
Utility helpers for the YouTube Fetch Videos Lambda service.

Provides logging utilities, SQS payload parsing, playlist traversal, and database
interaction helpers used to persist uploaded video metadata.
"""
import json
import logging
import os
import sys
import boto3
import psycopg
from typing import List, Tuple, Dict, Any
from datetime import datetime, timezone, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Constants
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
YOUTUBE_API_VERSION = "v3"
MAX_RESULTS_PER_REQUEST = 50

def get_logger(name: str) -> logging.Logger:
    """
    Return a logger configured for Lambda-friendly structured output.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Configured logger instance with stdout handler when running locally.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Only add handler if not already added
    if not logger.handlers and not os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger

def get_authenticated_service() -> Any:
    """
    Authenticate with the YouTube Data API using credentials stored in Secrets Manager.
    
    Returns:
        Authenticated YouTube API service object ready for playlist operations.
        
    Raises:
        ValueError: If required environment variables are not set
        Exception: If unable to retrieve or parse credentials
    """
    logger = get_logger(__name__)
    logger.info("Authenticating with YouTube API")

    secret_name = os.getenv("GOOGLE_SERVICE_ACCOUNT_SECRET")
    if not secret_name:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_SECRET environment variable not set")

    sm = boto3.client("secretsmanager")
    secret = sm.get_secret_value(SecretId=secret_name)
    creds_info = json.loads(secret["SecretString"])

    creds = Credentials.from_authorized_user_info(creds_info, YOUTUBE_SCOPES)
    return build("youtube", YOUTUBE_API_VERSION, credentials=creds)

def process_sqs_message(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract the payload dictionary from the incoming SQS event.

    Args:
        event: Lambda event containing SQS records serialized by AWS.

    Returns:
        Parsed JSON payload from the first record's body.

    Raises:
        KeyError, IndexError, json.JSONDecodeError when the event is malformed.
    """
    logger = get_logger(__name__)

    try:
        logger.info(f"Processing SQS event with {len(event.get('Records', []))} record(s)")
        msg_body = json.loads(event["Records"][0]["body"])
        logger.info(f"Extracted payload from sqs: {msg_body}")
        return msg_body
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.error(f"Failed to parse SQS message: {e}")
        raise

def get_playlist_items(targetPlaylistId:str,last_video_published_at) -> List[Tuple]:
    """
    Retrieve recent playlist items for the provided uploads playlist identifier.

    Args:
        targetPlaylistId: The uploads playlist whose videos should be inspected.
        video_published_at: Optional ISO timestamp to resume from, empty for default window.

    Returns:
        List of tuples containing video id, title, and publication datetime for recent uploads.
    """
    logger = get_logger(__name__)

    # Invoking authentication to Youtube Data API
    youtube = get_authenticated_service()
    logger.info(f"Initialized YouTube client for playlist {targetPlaylistId}")

    next_page_token = None
    allVideoDetails = []
    should_stop = False

    if last_video_published_at:
        utc_minus_days = datetime.fromisoformat(
            str(last_video_published_at).replace("Z", "+00:00")
        )
        logger.info(f"Resuming from last published at {utc_minus_days.isoformat()}")
    else:
        utc_now = datetime.now(timezone.utc)
        utc_minus_days = utc_now - timedelta(days=3)
        logger.info(
            f"No reference timestamp provided; defaulting to videos since {utc_minus_days.isoformat()}"
        )

    try:
        while True:
            # Request subscriptions
            request = youtube.playlistItems().list(
                playlistId = targetPlaylistId,
                part='snippet,contentDetails,id',
                maxResults=10,
                pageToken=next_page_token
            )
            response = request.execute()

            videoIdsList = response.get('items', [])
            logger.info(
                f"Fetched {len(videoIdsList)} playlist item(s) for token {next_page_token or 'initial'}"
            )

            for eachVideoId in videoIdsList:
                videoId = eachVideoId["contentDetails"]["videoId"]
                videoPublishedAt = eachVideoId["contentDetails"]["videoPublishedAt"]
                videoTitle = eachVideoId["snippet"]["title"]

                video_published = datetime.fromisoformat(videoPublishedAt.replace('Z','+00:00'))

                if video_published >= utc_minus_days:
                    allVideoDetails.append((videoId,videoTitle,video_published))
                else:
                    should_stop = True
                    break
            
            if should_stop:
                break

            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break
            
        logger.info(
            f"Collected {len(allVideoDetails)} eligible video(s) from playlist {targetPlaylistId}"
        )
        return allVideoDetails
    
    except HttpError as e:
        logger.error(f"An HTTP error occurred: {e}")
        raise

def prepare_records_to_insert(payload: Dict[str, Any], allVideoDetails: List[Tuple]) -> List[Tuple]:
    """
    Transform playlist items into tuples ready for PostgreSQL insertion.

    Args:
        payload: Channel metadata pulled from SQS.
        allVideoDetails: Collection of (videoId, title, published_at) tuples from YouTube.

    Returns:
        List of tuples ordered to match the all_uploaded_videos table schema.
    """
    logger = get_logger(__name__)
    
    batch_id = payload["batch_id"]
    channel_id = payload["channel_id"]
    channel_title = payload["channel_title"]
    uploads_playlist_id = payload["uploads_playlist_id"]

    data_to_insert = []

    for videoId,videoTitle,video_published in allVideoDetails:
        data_to_insert.append((channel_id,channel_title,videoId,videoTitle,video_published,uploads_playlist_id,batch_id))
    
    logger.info(f"{len(data_to_insert)} records prepared to insert into the database table")
    
    return data_to_insert

def db_interaction(data_to_insert: List[Tuple],batch_id:str,channel_title:str):
    """
    Insert prepared upload metadata rows into the PostgreSQL all_uploaded_videos table.
    
    Database credentials are retrieved from AWS Secrets Manager before establishing a
    connection and batch inserting the provided tuples.
    """
    logger = get_logger(__name__)

    # Fetch database connection string from Secrets Manager
    secret_name = os.getenv("POSTGRES_DB_URL")
    if not secret_name:
        raise ValueError("POSTGRES_DB_URL environment variable not set")

    logger.info("Fetching database secrets from AWS Secrets Manager")

    try:
        sm = boto3.client("secretsmanager")
        secret = sm.get_secret_value(SecretId=secret_name)
        db_secrets = json.loads(secret["SecretString"])
        conn_string = db_secrets["DB_URL"]
    except Exception:
        logger.exception("Error fetching database URL from secrets")
        raise

    logger.info("Connecting to PostgreSQL database")

    try:
        with psycopg.connect(conn_string) as conn:
            cur = conn.cursor()
            
            # Insert records
            logger.info(f"Inserting {len(data_to_insert)} record(s)")

            cur.executemany(
                "INSERT INTO all_uploaded_videos (channel_id,channel_title,video_id,video_title,video_published_at,uploads_playlist_id,batch_id) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (video_id) DO NOTHING;",
                data_to_insert,
            )
    except Exception:
        logger.exception("Error inserting data into database table")
        raise

    try:
        with psycopg.connect(conn_string) as conn:
            cur = conn.cursor()

            cur.execute(
                "SELECT COUNT(1) FROM all_uploaded_videos WHERE batch_id = %s AND channel_title = %s",
                (batch_id, channel_title),
            )
            inserted_count = cur.fetchone()[0]

            ip_count = len(data_to_insert)
            
            if ip_count == inserted_count:
                logger.info("All records inserted successfully")
            else:
                logger.info(f"{inserted_count} out of {ip_count} inserted successfully")

    except Exception:
        logger.exception("Error reading data from database table")
        raise
