"""
YouTube Subscriptions utility functions for Lambda functions.

This module provides utilities for authenticating with YouTube API,
fetching subscriptions, and writing results to S3.
"""
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import boto3
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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
    if not logger.handlers:
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

def list_subscriptions(youtube: Any) -> List[Dict[str, str]]:
    """
    List all channels the authenticated user is subscribed to.
    
    Args:
        youtube: Authenticated YouTube API service object
        
    Returns:
        List of subscription dictionaries with channel info
        
    Raises:
        Exception: If unable to fetch subscriptions from YouTube API
    """
    logger = get_logger(__name__)
    logger.info("Starting to fetch all YouTube channel subscriptions")

    subscriptions: List[Dict[str, str]] = []
    next_page_token: Optional[str] = None
    
    try:
        while True:
            # Request subscriptions
            request = youtube.subscriptions().list(
                part="snippet,contentDetails",
                mine=True,
                maxResults=MAX_RESULTS_PER_REQUEST,
                pageToken=next_page_token
            )
            response = request.execute()
            
            # Process each subscription
            for item in response.get("items", []):
                subscription_info = {
                    "channel_id": item["snippet"]["resourceId"]["channelId"],
                    "channel_title": item["snippet"]["title"],
                    "description": item["snippet"]["description"],
                    "published_at": item["snippet"]["publishedAt"]
                }
                subscriptions.append(subscription_info)
            
            # Check if there are more pages to process
            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break
       
        logger.info(f"Total subscriptions fetched: {len(subscriptions)}")
        return subscriptions
    
    except HttpError as e:
        logger.exception(f"YouTube API error fetching subscriptions: {e}")
        raise
    except Exception as e:
        logger.exception(f"Unexpected error fetching subscriptions: {e}")
        raise

def write_files_to_s3(subscriptions: List[Dict[str, str]]) -> bool:
    """
    Write subscriptions to S3 as JSON file.
    
    Args:
        subscriptions: List of subscription dictionaries
        
    Returns:
        True if write was successful
        
    Raises:
        ValueError: If required environment variables are not set
        Exception: If unable to write to S3
    """
    logger = get_logger(__name__)

    bucket_name = os.getenv("S3_BUCKET")
    prefix = os.getenv("S3_PREFIX")
    
    if not bucket_name or not prefix:
        raise ValueError("S3_BUCKET and S3_PREFIX environment variables must be set")

    try:
        s3_client = boto3.client("s3")
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        key = f"{prefix}/subscriptions_{timestamp}.json"
        
        s3_client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=json.dumps(subscriptions, indent=2),
            ContentType="application/json"
        )

        logger.info(f"Successfully written subscriptions to s3://{bucket_name}/{key}")
        return True
        
    except Exception as e:
        logger.exception(f"Error writing subscriptions to S3: {e}")
        raise