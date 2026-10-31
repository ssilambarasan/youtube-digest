"""
YouTube Subscriptions utility functions for Lambda functions.

This module provides utilities for authenticating with YouTube API,
fetching subscriptions, and writing results to S3.
"""
import json
import logging
import os
import sys
import boto3
import psycopg
from typing import Any, Dict, List, Optional, Tuple
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pathlib import Path


# Constants
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
YOUTUBE_API_VERSION = "v3"
MAX_RESULTS_PER_REQUEST = 50

def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger instance.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Configured logger instance
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
    Authenticate with YouTube API using service account credentials from Secrets Manager.
    
    Returns:
        Authenticated YouTube API service object
        
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

def load_scoped_subscriptions() -> List[dict]:

    logger = get_logger(__name__)

    try:
        # Loading scoped subscriptions from json file
        logger.info("Loading scoped channels from subscriptions")

        file_path = Path(__file__).parent / 'scoped_subscriptions.json'
        with open(file_path, 'r', encoding='utf-8') as f:
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
    Fetches upload playlist id for a youtube channel.
    """  
    
    logger = get_logger(__name__)

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

def db_interaction(enriched_channels: List[Tuple]) -> None:
    """
    Insert enriched channel data into PostgreSQL database.
    
    Truncates the scoped_channels table and inserts the provided enriched channel records.
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

            # Truncate table
            cur.execute("TRUNCATE TABLE scoped_channels;")
            logger.info("Table truncated successfully")
            
            # Insert records
            if enriched_channels:
                logger.info(f"Inserting {len(enriched_channels)} record(s)")
                cur.executemany(
                    "INSERT INTO scoped_channels (channel_id, channel_title, description, published_at, uploads_playlist_id) VALUES (%s, %s, %s, %s, %s);",
                    enriched_channels,
                )
                logger.info(f"Successfully inserted {len(enriched_channels)} record(s)")
            else:
                logger.warning("No enriched channels provided for insertion")
    except Exception:
        logger.exception("Error with database interaction")
        raise

def enrich_upload_playlistid(youtube: Any, channels: List[Dict[str, Any]]) -> List[Tuple]:
    """
    Enrich channel data with uploads playlist IDs from YouTube API.
    
    Fetches the uploads playlist ID for each channel and combines it with the original
    channel data. Skips channels with missing required fields and logs warnings.
    
    Args:
        youtube: Authenticated YouTube API service object
        channels: List of channel dictionaries containing at least 'channel_id' and 
                 'channel_title' keys
        
    Returns:
        List of tuples containing (channel_id, channel_title, description, published_at, 
        uploads_playlist_id) for successfully enriched channels
        
    Raises:
        Exception: If an error occurs while fetching uploads playlist ID for any channel
        
    Note:
        Invalid entries (missing channel_id or channel_title) are skipped and logged as warnings
    """
    logger = get_logger(__name__)
    logger.info(f"Starting enrichment of {len(channels) if channels else 0} channel(s) with playlist IDs")

    if not channels:
        logger.warning("No channels provided for enrichment")
        return []

    enriched_channels = []
    failed_channels = []

    try:
        for channel in channels:
            channel_id = channel.get("channel_id")
            channel_title = channel.get("channel_title")

            if not channel_id or not channel_title:
                logger.warning(f"Skipping invalid entry: Missing channel_id or channel_title - {channel}")
                failed_channels.append(channel)
            else:
                try:
                    logger.debug(f"Processing channel: {channel_title} (ID: {channel_id})")
                    logger.info(f"Fetching uploads playlist ID for channel: {channel_title}")

                    uploadsPlaylistId = get_uploads_playlist_id(youtube, channel_id)

                    description = channel.get("description")
                    published_at = channel.get("published_at")
                    
                    enriched_channels.append((channel_id, channel_title, description, published_at, uploadsPlaylistId))
                    logger.debug(f"Successfully enriched channel {channel_title} with playlist ID: {uploadsPlaylistId}")
                    
                except Exception as e:
                    logger.error(f"Failed to enrich channel {channel_title} (ID: {channel_id}): {str(e)}")
                    failed_channels.append(channel)
        
        logger.info(f"Enrichment completed: {len(enriched_channels)} successful, {len(failed_channels)} failed")
        return enriched_channels
    
    except Exception:
        logger.exception("Error enriching upload playlist ids for channels")
        raise