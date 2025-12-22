import os
import json
import isodate
import logging
import shutil
import smtplib
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from auth.authentication import get_authenticated_service
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from googleapiclient.errors import HttpError
from google import genai
from google.genai.types import Part, HttpOptions
from typing import Tuple, List, Dict
from pathlib import Path

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PAYLOAD_CONFIG_FILE = DATA_DIR / "payload_config.json"
BATCH_DATA_DIR = DATA_DIR / "batches"

def create_cleanup_batch_folder(batch_id_folder: Path) -> None:
    try:
        if batch_id_folder.exists():
            logger.info(f"{batch_id_folder.name} folder available")
            logger.info("Cleaning up the folder")
            shutil.rmtree(batch_id_folder)

        batch_id_folder.mkdir()
        logger.info(f"{batch_id_folder.name} folder created successfully under batches")

    except Exception as e:
        logger.exception("Error creating / cleaning up batchid folder")
        raise

def load_batch_channel_details() -> List[Tuple[str,str]]:

    channel_details = []
    # Fetching all channels from scoped subscribtions
    logger.info("Fetching channel details for batch")

    with open(PAYLOAD_CONFIG_FILE,'r',encoding='utf-8') as f:
        content = json.load(f)
    
    if not content:
        raise ValueError(f"No channel details found in the {PAYLOAD_CONFIG_FILE.name} file")
    
    for each in content:
        channel_id = each.get("channel_id")
        channel_title = each.get("channel_title")
        uploads_playlist_id = each.get("uploadsPlaylistId")

        if not channel_id or not channel_title or not uploads_playlist_id:
            logger.warning(f"Skipping invalid entry: {each}")
        else:
            channel_details.append((channel_id,channel_title,uploads_playlist_id))

    if not channel_details:
        raise ValueError("No valid channel entries found")
    
    logger.info("Channel details fetch complete for batch processing")
    return channel_details

def get_playlist_items(youtube, targetPlaylistId:str):
    """
    List all channels the authenticated user is subscribed to.
    """
    next_page_token = None
    allVideoIds = []
    should_stop = False

    utc_now = datetime.now(timezone.utc)
    utc_minus_days = utc_now - timedelta(days=4)
   
    try:
        while True:
            # Request subscriptions
            request = youtube.playlistItems().list(
                playlistId = targetPlaylistId,
                part='snippet,contentDetails,id',
                maxResults=5,
                pageToken=next_page_token
            )
            response = request.execute()

            videoIdsList = response.get('items', [])

            for eachVideoId in videoIdsList:
                videoId = eachVideoId["contentDetails"]["videoId"]
                videoPublishedAt = eachVideoId["contentDetails"]["videoPublishedAt"]
                # videoTitle = eachVideoId["snippet"]["title"]

                video_published = datetime.fromisoformat(videoPublishedAt.replace('Z','+00:00'))

                if video_published >= utc_minus_days:
                    allVideoIds.append(videoId)
                else:
                    should_stop = True
                    break
            
            if should_stop:
                break

            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break
    
    except HttpError as e:
        logger.error(f"An HTTP error occurred: {e}")
           
    return allVideoIds

def write_batch_config_to_file(BATCH_CONFIG_FILE:Path, config: List[dict]) -> None:
    # Optionally save to a JSON file
    logger.info("Writing the batch configuration to a file on data folder")

    try:
        with open(BATCH_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        logger.info("Batch configurations successfully saved to data folder")
    except Exception as e:
        logger.exception("Failed to write batch configuration to file")
        raise

def determine_video_duration_and_shorts(duration_str:str) -> Tuple[int,bool]:

    duration = isodate.parse_duration(duration_str)
    total_seconds = int(duration.total_seconds())
      
    if total_seconds <= 180:
        return (total_seconds, True)
    else:
        return (total_seconds, False)

def process_each_video(youtube,allVideoIds) -> List[dict]:

    video_metadata_list = []

    for eachVideoId in allVideoIds:

        video_metadata_dict = {}

        logger.info(f"Processing youtube videoId: {eachVideoId}")

        video_metadata_dict['videoId'] = eachVideoId

        request = youtube.videos().list(
            part='contentDetails,snippet',
            id=eachVideoId)
        response = request.execute()

        video_title = response.get('items')[0].get('snippet').get('title')
        videoLength = response.get('items')[0].get('contentDetails').get('duration')

        video_metadata_dict['videoTitle'] = video_title

        total_seconds, is_short = determine_video_duration_and_shorts(videoLength)
        video_metadata_dict['videoLengthSecs'] = total_seconds

        if is_short:
            video_metadata_dict['isShort'] = True
        else:
            video_metadata_dict['isShort'] = False
        
        video_metadata_list.append(video_metadata_dict)

    return video_metadata_list

def summarize_youtube_video(videoURL:str):

    prompt = """
        Summarize this YouTube video concisely. Keep it brief and actionable. Focus on what matters.

        Return plain text in EXACTLY this format (including blank lines and bullet style):

        <1 sentence main topic>

        Key points:
        * <bullet 1>
        * <bullet 2>
        * <bullet 3>

        Important takeaways/action items:
        * <bullet 1>
        * <bullet 2>

        Rules:
        - Put each bullet on its own line.
        - Do not use bold (**), numbering, or inline bullets.
        """
    
    projectId = os.getenv("PROJECT_ID")
    region = "us-central1"  # Hardcoded to avoid conflict with AWS REGION env var, repace this based on your region for Google Vertex API
    
    client = genai.Client(
        vertexai=True,
        http_options=HttpOptions(api_version="v1"),
        project=projectId,
        location=region
    )

    result = False
    response = None

    try:
        logger.info(f"Attempting with URL: {videoURL}")
        
        # Define the multimodal prompt
        contents = [
            Part.from_uri(
                file_uri=videoURL,
                mime_type="video/mp4",
            ),
            prompt,
        ]

        logger.info("Sending request to Gemini on Vertex AI...")
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
        )
        
        result = response.text
        # logger.debug(result)

    except Exception as e:
        logger.exception("Error creating / cleaning up batchid folder")
        raise
    
    return result

def create_email_html(shorts: Dict[str, List[dict]], longs: Dict[str, List[dict]]) -> str:
    """Create HTML email content from shorts and long videos."""
    
    html = """
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
            h1 { color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px; }
            h2 { color: #5f6368; margin-top: 30px; }
            h3 { color: #202124; margin-top: 20px; }
            .channel { margin-bottom: 30px; padding: 15px; background-color: #f8f9fa; border-radius: 8px; }
            .video { margin: 15px 0; padding: 10px; background-color: white; border-left: 3px solid #1a73e8; }
            .video-title { font-weight: bold; color: #1a73e8; text-decoration: none; }
            .video-title:hover { text-decoration: underline; }
            .summary { margin-top: 8px; color: #5f6368; line-height: 1.6; white-space: pre-wrap; }
            .shorts-list { list-style: none; padding-left: 0; }
            .shorts-list li { margin: 8px 0; }
        </style>
    </head>
    <body>
        <h1>📺 YouTube Digest</h1>
    """
    
    # Add long videos section
    if longs:
        total_longs = sum(len(videos) for videos in longs.values())
        html += f"<h2>📹 Long Videos ({total_longs})</h2>"
        for channel, videos in longs.items():
            html += f'<div class="channel"><h3>{channel}</h3>'
            for video in videos:
                html += f'''
                <div class="video">
                    <a href="{video['link']}" class="video-title">{video['title']}</a>
                    <div class="summary">{video['summary']}</div>
                </div>
                '''
            html += '</div>'
    
    # Add shorts section
    if shorts:
        total_shorts = sum(len(videos) for videos in shorts.values())
        html += f"<h2>⚡ Shorts ({total_shorts})</h2>"
        for channel, videos in shorts.items():
            html += f'<div class="channel"><h3>{channel}</h3><ul class="shorts-list">'
            for video in videos:
                html += f'<li>🎬 <a href="{video["link"]}" class="video-title">{video["title"]}</a></li>'
            html += '</ul></div>'
    
    html += """
    </body>
    </html>
    """
    
    return html

def send_email(
    subject: str,
    html_content: str,
    smtp_server: str = 'smtp.gmail.com',
    smtp_port: int = 587
):
    """Send email using SMTP."""
    
    # Get credentials from environment
    from_email = os.getenv('gmail_sender_email')
    to_email = os.getenv('gmail_sender_email')
    password = os.getenv('gmail_app_password')  # Use App Password for Gmail
    
    if not from_email or not password:
        raise ValueError("Email credentials not found in environment variables")
    
    # Create message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email
    
    # Attach HTML content
    html_part = MIMEText(html_content, 'html')
    msg.attach(html_part)
    
    # Send email
    try:
        logger.info(f"Sending email to {to_email}")
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(from_email, password)
            server.send_message(msg)
        logger.info("Email sent successfully")
    except Exception as e:
        logger.exception("Failed to send email")
        raise

def main():
    """
    Main function to authenticate and list subscriptions.
    """

    logger.info("Starting to process payloads batch")

    try:
        logger.info("Creating batch id and folder for processing")

        batch_id = datetime.now().strftime('%m%d%Y')
        # batch_id = "12192025"
        batch_id_folder = BATCH_DATA_DIR / batch_id

        create_cleanup_batch_folder(batch_id_folder)

        channels = load_batch_channel_details()

        # Invoking authentication to Youtube Data API
        youtube = get_authenticated_service()

        ##################################################################
        # Fetch all Video Ids from the Uploads Playlist of a channel.
        ##################################################################

        logger.info("*" * 75)
        logger.info("Fetching channel videos for last 1 days")
        logger.info("*" * 75)
       
        batch_config_list_dicts = []

        for eachChannelId, eachChannelName, eachUploadsPlaylistId in channels:
            allVideoIds = get_playlist_items(youtube, eachUploadsPlaylistId)

            if allVideoIds:
                logger.info(f"{eachChannelName} - {len(allVideoIds)} videos found")
                
                video_metadata_list = process_each_video(youtube,allVideoIds)

                videoids_by_channel = {
                        "channel_id": eachChannelId,
                        "channel_title": eachChannelName,
                        "uploadsPlaylistId": eachUploadsPlaylistId,
                        "videsIds": video_metadata_list
                    }
                
                batch_config_list_dicts.append(videoids_by_channel)
            else:
                logger.info(f"{eachChannelName} - No Videos Found")
            
            logger.info("-" * 75)

        ###################################################################
        # Writing batch configuration as file to the batch folder under data
        ###################################################################

        logger.info("*" * 75)
        logger.info("Writing batch configuration as file")
        logger.info("*" * 75)

        batch_config_file = batch_id_folder / "batch_config.json"
        write_batch_config_to_file(batch_config_file,batch_config_list_dicts)

        ###################################################################
        # Orgnize email content
        ###################################################################

        shorts_by_channel = {}
        long_videos_by_channel = {}

        for eachChannel in batch_config_list_dicts:
            channal_name = eachChannel.get('channel_title')
            videoIds = eachChannel.get('videsIds')

            shorts = []
            longs = []

            for eachVideo in videoIds:
                videoId = eachVideo['videoId']
                video_title = eachVideo['videoTitle']

                if eachVideo['isShort']:
                    video_url = f"https://www.youtube.com/shorts/{videoId}"
                    shorts.append({
                        'title': video_title,
                        'link': video_url
                    })
                else:
                    video_url = f"https://www.youtube.com/watch?v={videoId}"

                    status = summarize_youtube_video(video_url)

                    if status:
                        longs.append({
                            'title': video_title,
                            'link': video_url,
                            'summary': status
                        })
                    else:
                        logger.info(f"Skipping video {video_title}, check logs for more details")

            if shorts:
                shorts_by_channel[channal_name] = shorts
            if longs:
                long_videos_by_channel[channal_name] = longs
        
        # Generate and send email
        logger.info("Generating email content")
        email_html = create_email_html(shorts_by_channel, long_videos_by_channel)

        subject = f"YouTube Digest - {datetime.now().strftime('%B %d, %Y')}"

        send_email(
            subject=subject,
            html_content=email_html
        )

    except Exception as e:
        logger.exception("Error in processing payloads batch")

if __name__ == '__main__':

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info("Loading environment variables")
    load_dotenv(override=True)

    main()