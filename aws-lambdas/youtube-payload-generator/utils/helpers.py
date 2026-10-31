"""
Utility functions for YouTube payload generator Lambda service.

Provides logging configuration and database interaction utilities for
fetching channel subscription data from PostgreSQL.
"""
import json
import logging
import os
import sys
import boto3
import psycopg
from typing import List, Tuple

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

def db_interaction() -> List[Tuple]:
    """
    Fetch scoped channel data from PostgreSQL database.
    
    Retrieves channel subscriptions with their metadata and uploads playlist IDs
    from the scoped_channels table. Database credentials are fetched from 
    AWS Secrets Manager.
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

            query = """
                SELECT p.channel_id,
                    p.channel_title,
                    p.uploads_playlist_id,
                    MAX(c.video_published_at) AS last_video_published_at
                FROM scoped_channels p
                LEFT JOIN all_uploaded_videos c ON p.channel_id = c.channel_id
                GROUP BY p.channel_id, p.channel_title, p.uploads_playlist_id
                ORDER BY last_video_published_at;
            """
            
            # select data from table
            cur.execute(query)

            result = cur.fetchall()

            if result:
                logger.info(f"Total rows retrieved: {cur.rowcount}")
                return result
            else:
                logger.info("No records retrieved from database table")
                raise

    except Exception:
        logger.exception("Error with database interaction")
        raise


