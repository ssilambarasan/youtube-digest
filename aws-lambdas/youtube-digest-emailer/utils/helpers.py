"""Utility helpers that power the YouTube Digest Emailer Lambda."""
import json
import logging
import os
import sys
import boto3
import psycopg
from typing import List, Tuple, Any
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from collections import defaultdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

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

def db_interaction() -> List[Tuple]:
    """Fetch (batch_id, channel_title, video_title) tuples for the latest digest batch."""
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
                SELECT batch_id,channel_title,video_title from all_uploaded_videos 
                where batch_id = (select max(batch_id) from all_uploaded_videos)
                order by channel_id,video_published_at;
            """
            
            # select data from table
            cur.execute(query)

            result = cur.fetchall()

            logger.info(f"{len(result)} videos pulled from the database table")
            return result

    except Exception:
        logger.exception("Error with database interaction")
        raise

def build_email_html(rows: List[Tuple]):
    """Generate digest HTML grouped by channel title from database rows.

    Args:
        rows: Sequence of tuples shaped as (batch_id, channel_title, video_title).

    Returns:
        Tuple containing the batch identifier and rendered HTML string.
    """

    grouped = defaultdict(list)
    c_batch_id = ""
    logger = get_logger(__name__)

    for batch_id,channel_title,video_title in rows:
        c_batch_id = batch_id
        grouped[channel_title].append(video_title)

    html = """
    <html>
    <body style="font-family: Arial, sans-serif;">
      <h2>📺 Uploaded Videos</h2>
    """

    for channel, videos in grouped.items():
        html += f"""
        <div>
          <strong style="font-size:16px;">{channel}</strong>
          <ul style="padding-left:16px; margin-top:6px;">
        """
        for v in videos:
            html += f"<li>{v}</li>"
        html += "</ul></div>"

    html += """
    </body>
    </html>
    """
    logger.info(
        "Prepared digest HTML for %s channels and %s videos",
        len(grouped),
        sum(len(v) for v in grouped.values()),
    )
    return c_batch_id, html

def send_email(subject: str, html_content: str):
    """Send the rendered digest HTML via Gmail SMTP using app credentials.

    Args:
        subject: Email subject line (includes the digest batch identifier).
        html_content: HTML body produced by ``build_email_html``.
    """

    logger = get_logger(__name__)

    # Fetch Gmail credentials from Secrets Manager
    secret_name = os.getenv("GMAIL_APP_CREDS")
    if not secret_name:
        raise ValueError("GMAIL_APP_CREDS environment variable not set")

    logger.info("Fetching gmail app credentials from AWS Secrets Manager")

    try:
        sm = boto3.client("secretsmanager")
        secret = sm.get_secret_value(SecretId=secret_name)
        gmail_secrets = json.loads(secret["SecretString"])
        
        from_email = gmail_secrets["email"]
        to_email = from_email
        password = gmail_secrets["password"]
    except Exception:
        logger.exception("Error fetching database URL from secrets")
        raise

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    msg.attach(MIMEText(html_content, "html"))

    logger.info("Sending digest email with subject '%s' to %s", subject, to_email)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(from_email, password)
        server.send_message(msg)
    logger.info("Digest email sent successfully")