import logging
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build, Resource

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
AUTH_DIR = Path(__file__).resolve().parent

SCOPES = ['https://www.googleapis.com/auth/youtube.readonly']

def get_authenticated_service() -> Resource:
    """
    Authenticate and return the YouTube API service object.
    """

    logger.info("Authenticating with YouTube API")
    
    creds = None
    token_file = AUTH_DIR / "token.json"
    client_secret_file = AUTH_DIR / "client_secret.json"

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    
    try:
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(client_secret_file), SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save the credentials for the next run
            with open(token_file, 'w') as token:
                token.write(creds.to_json())

        logger.info("Authentication successful")
        
        return build('youtube', 'v3', credentials=creds)
    
    except Exception as e:
        logger.exception(f"Authentication failed: {e}")
        raise