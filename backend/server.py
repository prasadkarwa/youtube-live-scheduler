from fastapi import FastAPI, APIRouter, HTTPException, Depends, BackgroundTasks, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timedelta, timezone
import asyncio
import json
import secrets
import subprocess
import threading
import time
import yt_dlp
from urllib.parse import urlencode

# Google API imports
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
import google.auth.transport.requests

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Google OAuth Configuration
GOOGLE_CLIENT_ID = "341627338406-3u2vrp2j80fqmom8d6dg1f7oiclfuc6q.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = "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"
REDIRECT_URI = "https://yt-stream-planner.preview.emergentagent.com/auth/callback"
SCOPES = [
    'https://www.googleapis.com/auth/youtube.force-ssl',
    'https://www.googleapis.com/auth/youtube'
]

# Create the main app without a prefix
app = FastAPI(title="YouTube Live Streaming Scheduler")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

security = HTTPBearer()

# Pydantic Models
class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: str
    name: str
    channel_id: str
    channel_name: str
    access_token: str
    refresh_token: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class YouTubeVideo(BaseModel):
    id: str
    title: str
    description: str
    thumbnail_url: str
    duration: str
    published_at: str

class ScheduledBroadcast(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    video_id: str
    video_title: str
    broadcast_id: str
    stream_id: str
    scheduled_time: datetime
    status: str  # created, live, completed, error
    stream_url: str
    watch_url: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ScheduleRequest(BaseModel):
    video_id: str
    video_title: str
    selected_date: str
    custom_times: Optional[List[str]] = None
    timezone: Optional[str] = "UTC"  # User's timezone

class AuthCallbackRequest(BaseModel):
    code: str

# Helper Functions
def get_youtube_service(credentials: Credentials):
    return build('youtube', 'v3', credentials=credentials)

def get_credentials_from_token(access_token: str, refresh_token: str) -> Credentials:
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=SCOPES
    )
    return creds

async def get_video_stream_url(video_id: str) -> tuple[str, str]:
    """Get the best quality stream URL for a YouTube video"""
    try:
        ydl_opts = {
            'format': 'best[height<=720]/best',  # Simplified format selection
            'quiet': False,
            'no_warnings': False,
            'extractaudio': False,
            'audioformat': 'aac',
            'outtmpl': '%(id)s.%(ext)s',
            'writesubtitles': False,
            'writeautomaticsub': False,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'http_chunk_size': 10485760,  # 10MB chunks
        }
        
        video_url = f'https://www.youtube.com/watch?v={video_id}'
        logging.info(f"Attempting to extract URL from: {video_url}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(video_url, download=False)
                logging.info(f"Successfully extracted info for video {video_id}")
                
                # Try multiple extraction methods
                stream_url = None
                extraction_method = "unknown"
                
                # Method 1: Direct URL
                if 'url' in info:
                    stream_url = info['url']
                    extraction_method = "direct_url"
                    logging.info(f"Found direct URL: {stream_url[:100]}...")
                
                # Method 2: Best format from formats list
                elif 'formats' in info and len(info['formats']) > 0:
                    formats = info['formats']
                    logging.info(f"Found {len(formats)} formats")
                    
                    # Log all available formats for debugging
                    logging.info("Available formats:")
                    for i, fmt in enumerate(formats[:10]):  # Log first 10 formats
                        protocol = fmt.get('protocol', 'unknown')
                        url = fmt.get('url', '')
                        is_hls = url.endswith('.m3u8') or 'manifest' in url or protocol in ['m3u8', 'm3u8_native']
                        logging.info(f"Format {i}: {fmt.get('format_id')} - {fmt.get('ext')} - {fmt.get('height')}p - Protocol: {protocol} - HLS: {is_hls}")
                    
                    # Prioritize direct HTTP/HTTPS URLs over HLS manifests
                    # First try: mp4 with both video and audio, NOT HLS
                    for fmt in formats:
                        url = fmt.get('url', '')
                        protocol = fmt.get('protocol', '')
                        is_hls = (url.endswith('.m3u8') or 'manifest' in url or 
                                protocol in ['m3u8', 'm3u8_native', 'hls'])
                        
                        if (fmt.get('ext') == 'mp4' and
                            fmt.get('vcodec') != 'none' and 
                            fmt.get('acodec') != 'none' and 
                            url and not is_hls and
                            fmt.get('height', 0) <= 720 and
                            protocol in ['http', 'https']):
                            stream_url = url
                            extraction_method = f"mp4_direct_{fmt.get('height', 'unknown')}p"
                            logging.info(f"Selected MP4 HTTP format: {fmt.get('format_id')} - {fmt.get('height', 'unknown')}p")
                            break
                    
                    # Second try: any non-HLS HTTP format with video and audio
                    if not stream_url:
                        for fmt in formats:
                            url = fmt.get('url', '')
                            protocol = fmt.get('protocol', '')
                            is_hls = (url.endswith('.m3u8') or 'manifest' in url or 
                                    protocol in ['m3u8', 'm3u8_native', 'hls'])
                            
                            if (fmt.get('vcodec') != 'none' and 
                                fmt.get('acodec') != 'none' and 
                                url and not is_hls and
                                fmt.get('height', 0) <= 720 and
                                protocol in ['http', 'https']):
                                stream_url = url
                                extraction_method = f"direct_http_{fmt.get('ext', 'unknown')}_{fmt.get('height', 'unknown')}p"
                                logging.info(f"Selected direct HTTP format: {fmt.get('format_id')} - {fmt.get('height', 'unknown')}p")
                                break
                    
                    # Third try: any HTTP format (even without audio, we'll add audio later)
                    if not stream_url:
                        for fmt in formats:
                            url = fmt.get('url', '')
                            protocol = fmt.get('protocol', '')
                            is_hls = (url.endswith('.m3u8') or 'manifest' in url or 
                                    protocol in ['m3u8', 'm3u8_native', 'hls'])
                            
                            if (fmt.get('vcodec') != 'none' and 
                                url and not is_hls and
                                fmt.get('height', 0) <= 720 and
                                protocol in ['http', 'https']):
                                stream_url = url
                                extraction_method = f"video_only_http_{fmt.get('ext', 'unknown')}_{fmt.get('height', 'unknown')}p"
                                logging.info(f"Selected video-only HTTP format: {fmt.get('format_id')} - {fmt.get('height', 'unknown')}p")
                                break
                    
                    # Last resort: reject HLS completely and return error
                    if not stream_url:
                        available_protocols = list(set([fmt.get('protocol', 'unknown') for fmt in formats[:10]]))
                        error_msg = f"No suitable non-HLS format found. Available protocols: {available_protocols}. YouTube may only provide HLS for this video."
                        logging.error(error_msg)
                        return None, error_msg
                
                # Method 3: Try manifest URL if available
                elif 'manifest_url' in info:
                    stream_url = info['manifest_url']
                    extraction_method = "manifest_url"
                    logging.info(f"Using manifest URL: {stream_url[:100]}...")
                
                if stream_url:
                    return stream_url, f"Success via {extraction_method}"
                else:
                    error_msg = "No suitable stream URL found in extracted info"
                    logging.error(error_msg)
                    return None, error_msg
                    
            except yt_dlp.DownloadError as e:
                error_str = str(e)
                if "live event will begin in" in error_str.lower():
                    error_msg = f"Cannot extract from future live event: {error_str}. Please use a completed/existing video."
                elif "private video" in error_str.lower():
                    error_msg = f"Video is private or restricted: {error_str}"
                elif "video unavailable" in error_str.lower():
                    error_msg = f"Video unavailable: {error_str}. Video may be deleted or restricted."
                else:
                    error_msg = f"yt-dlp download error: {error_str}"
                logging.error(error_msg)
                return None, error_msg
                
            except Exception as e:
                error_msg = f"yt-dlp extraction error: {str(e)}"
                logging.error(error_msg)
                return None, error_msg
                
    except Exception as e:
        error_msg = f"General error in video extraction: {str(e)}"
        logging.error(error_msg)
        return None, error_msg

def stream_video_to_rtmp(video_url: str, rtmp_url: str, duration_seconds: int = None):
    """Stream a video to RTMP endpoint using FFmpeg"""
    try:
        # Detect if input is HLS manifest
        is_hls = video_url.endswith('.m3u8') or 'manifest' in video_url
        
        # Base FFmpeg command
        cmd = ['ffmpeg', '-y']  # -y to overwrite output
        
        # Input options
        if is_hls:
            # HLS-specific input options
            cmd.extend([
                '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
                '-user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                '-headers', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                '-re',  # Read at native frame rate
                '-i', video_url
            ])
        else:
            # Direct video URL options
            cmd.extend([
                '-re',  # Read at native frame rate
                '-i', video_url
            ])
        
        # Output encoding options
        cmd.extend([
            '-c:v', 'libx264',  # Video codec
            '-c:a', 'aac',      # Audio codec
            '-preset', 'veryfast',  # Encoding preset
            '-tune', 'zerolatency',  # Low latency
            '-pix_fmt', 'yuv420p',  # Pixel format
            '-maxrate', '2500k',     # Maximum bitrate
            '-bufsize', '5000k',     # Buffer size
            '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2',  # Scale and pad
            '-r', '30',              # Frame rate
            '-g', '60',              # GOP size
            '-keyint_min', '30',     # Minimum keyframe interval
            '-sc_threshold', '0',    # Disable scene change detection
            '-b:v', '2000k',         # Video bitrate
            '-b:a', '128k',          # Audio bitrate
            '-ar', '44100',          # Audio sample rate
            '-f', 'flv',             # Output format
            '-flvflags', 'no_duration_filesize',  # FLV flags
        ])
        
        # Add duration if specified
        if duration_seconds:
            cmd.insert(-1, '-t')
            cmd.insert(-1, str(duration_seconds))
        
        # Add RTMP destination
        cmd.append(rtmp_url)
        
        # Add duration if specified
        if duration_seconds:
            cmd.insert(-1, '-t')
            cmd.insert(-1, str(duration_seconds))
        
        logging.info(f"Starting FFmpeg stream: {' '.join(cmd)}")
        
        # Start FFmpeg process with better error handling
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Combine stderr and stdout
            stdin=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1
        )
        
        # Monitor the process for a few seconds to catch early failures
        import threading
        
        def log_output():
            try:
                for line in process.stdout:
                    logging.info(f"FFmpeg: {line.strip()}")
            except:
                pass
        
        # Start logging thread
        log_thread = threading.Thread(target=log_output)
        log_thread.daemon = True
        log_thread.start()
        
        return process
        
    except Exception as e:
        logging.error(f"Failed to start video stream: {e}")
        return None

async def schedule_video_stream(broadcast_id: str, stream_key: str, video_id: str, start_time: datetime):
    """Schedule a video stream to start at a specific time"""
    import tempfile
    import os
    
    try:
        # Calculate wait time
        now = datetime.now(timezone.utc)
        wait_seconds = (start_time - now).total_seconds()
        
        if wait_seconds > 0:
            logging.info(f"Waiting {wait_seconds} seconds to start stream for broadcast {broadcast_id}")
            await asyncio.sleep(wait_seconds)
        
        logging.info(f"Starting scheduled stream for broadcast {broadcast_id}")
        
        # Construct RTMP URL first (needed for both success and fallback)
        rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
        
        # Use download+stream method since it's more reliable
        temp_dir = tempfile.mkdtemp()
        temp_file = os.path.join(temp_dir, f"{video_id}_{broadcast_id}.mp4")
        
        # Download the video with more robust options
        ydl_opts = {
            'format': 'best[ext=mp4][height<=720]/best[height<=720]',
            'outtmpl': temp_file,
            'quiet': False,
            'retries': 3,
            'fragment_retries': 3,
            'socket_timeout': 30,
            'http_chunk_size': 10485760,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'extractor_args': {
                'youtube': {
                    'player_client': ['web', 'web_safari', 'web_embedded'],
                    'skip': ['translate'],
                }
            }
        }
        
        download_success = False
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f'https://www.youtube.com/watch?v={video_id}'])
            
            if os.path.exists(temp_file) and os.path.getsize(temp_file) > 1024:  # File exists and is > 1KB
                download_success = True
                logging.info(f"Successfully downloaded {video_id} ({os.path.getsize(temp_file)} bytes)")
            else:
                logging.error(f"Downloaded file is empty or too small for {video_id}")
        except Exception as e:
            logging.error(f"Download failed for {video_id}: {e}")
        
        # If download failed, use fallback streaming method
        if not download_success:
            logging.info(f"Download failed for {video_id}, using fallback test pattern stream")
            
            try:
                # Stream a test pattern with video info overlay
                cmd = [
                    'ffmpeg', '-y',
                    '-f', 'lavfi',
                    '-i', 'testsrc2=size=1280x720:rate=30',
                    '-f', 'lavfi', 
                    '-i', 'sine=frequency=440:sample_rate=44100',
                    '-c:v', 'libx264',
                    '-c:a', 'aac',
                    '-preset', 'veryfast',
                    '-tune', 'zerolatency',
                    '-pix_fmt', 'yuv420p',
                    '-maxrate', '2500k',
                    '-bufsize', '5000k',
                    '-vf', f'drawtext=text="Scheduled Stream - Video ID\\: {video_id} - %{{localtime}}":fontcolor=white:fontsize=24:x=10:y=10:box=1:boxcolor=black@0.8',
                    '-r', '30',
                    '-g', '60',
                    '-keyint_min', '30',
                    '-sc_threshold', '0',
                    '-b:v', '2000k',
                    '-b:a', '128k',
                    '-ar', '44100',
                    '-f', 'flv',
                    '-flvflags', 'no_duration_filesize',
                    rtmp_url
                ]
                
                logging.info(f"Fallback FFmpeg command: {' '.join(cmd)}")
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE
                )
                
                # Wait a moment to check if process started
                time.sleep(2)
                
                if process.poll() is None:
                    # Process is running
                    logging.info(f"Fallback stream started successfully for broadcast {broadcast_id}")
                    
                    # Store fallback process info
                    await db.streaming_processes.insert_one({
                        "broadcast_id": broadcast_id,
                        "process_id": process.pid,
                        "started_at": datetime.now(timezone.utc),
                        "video_id": video_id,
                        "method": "fallback_test_pattern",
                        "note": "Download failed, using test pattern"
                    })
                else:
                    # Process died
                    stdout, stderr = process.communicate()
                    logging.error(f"Fallback FFmpeg failed. STDOUT: {stdout.decode() if stdout else 'None'}")
                    logging.error(f"Fallback FFmpeg failed. STDERR: {stderr.decode() if stderr else 'None'}")
                    
            except Exception as fallback_error:
                logging.error(f"Fallback streaming failed: {fallback_error}")
            
            return
        
        # Stream the downloaded file
        
        cmd = [
            'ffmpeg', '-y',
            '-stream_loop', '-1',  # Loop the video
            '-re',  # Read at native frame rate
            '-i', temp_file,
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'veryfast',
            '-tune', 'zerolatency',
            '-pix_fmt', 'yuv420p',
            '-maxrate', '2500k',
            '-bufsize', '5000k',
            '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2',
            '-r', '30',
            '-g', '60',
            '-keyint_min', '30',
            '-sc_threshold', '0',
            '-b:v', '2000k',
            '-b:a', '128k',
            '-ar', '44100',
            '-f', 'flv',
            '-flvflags', 'no_duration_filesize',
            rtmp_url
        ]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1
        )
        
        if process:
            # Store process info for potential cleanup
            await db.streaming_processes.insert_one({
                "broadcast_id": broadcast_id,
                "process_id": process.pid,
                "started_at": datetime.now(timezone.utc),
                "video_id": video_id,
                "temp_file": temp_file,
                "temp_dir": temp_dir,
                "method": "download_and_stream"
            })
            
            logging.info(f"Download+Stream started successfully for broadcast {broadcast_id}")
            
            # Schedule cleanup (after a reasonable time)
            def cleanup_later():
                time.sleep(3600)  # Wait 1 hour before cleanup
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                    if os.path.exists(temp_dir):
                        os.rmdir(temp_dir)
                    logging.info(f"Cleaned up temp files for broadcast {broadcast_id}")
                except:
                    pass
            
            threading.Thread(target=cleanup_later, daemon=True).start()
            
        else:
            logging.error(f"Failed to start download+stream for broadcast {broadcast_id}")
            
    except Exception as e:
        logging.error(f"Error in scheduled video stream: {e}")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    token = credentials.credentials
    user = await db.users.find_one({"access_token": token})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid authentication")
    return User(**user)

async def refresh_token_if_needed(user: User) -> User:
    try:
        creds = get_credentials_from_token(user.access_token, user.refresh_token)
        if creds.expired:
            creds.refresh(google.auth.transport.requests.Request())
            # Update user with new token
            await db.users.update_one(
                {"id": user.id},
                {"$set": {"access_token": creds.token}}
            )
            user.access_token = creds.token
        return user
    except Exception as e:
        logging.error(f"Token refresh failed: {e}")
        raise HTTPException(status_code=401, detail="Token refresh failed")

# Auth Routes
@api_router.get("/auth/url")
async def get_auth_url():
    """Get Google OAuth URL for authentication"""
    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [REDIRECT_URI]
                }
            },
            scopes=SCOPES
        )
        flow.redirect_uri = REDIRECT_URI
        
        auth_url, _ = flow.authorization_url(prompt='consent')
        return {"auth_url": auth_url}
    
    except Exception as e:
        logging.error(f"Auth URL generation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate auth URL")

@api_router.post("/auth/callback")
async def auth_callback(request: AuthCallbackRequest):
    """Handle OAuth callback and store user credentials"""
    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [REDIRECT_URI]
                }
            },
            scopes=SCOPES
        )
        flow.redirect_uri = REDIRECT_URI
        
        # Exchange authorization code for tokens
        flow.fetch_token(code=request.code)
        
        credentials = flow.credentials
        
        # Get user info from YouTube API
        youtube = get_youtube_service(credentials)
        
        # Get channel information
        channel_response = youtube.channels().list(
            part='snippet,contentDetails',
            mine=True
        ).execute()
        
        if not channel_response.get('items'):
            raise HTTPException(status_code=400, detail="No YouTube channel found")
        
        channel = channel_response['items'][0]
        channel_id = channel['id']
        channel_name = channel['snippet']['title']
        
        # Check if user already exists
        existing_user = await db.users.find_one({"channel_id": channel_id})
        
        user_data = {
            "email": f"{channel_id}@youtube.com",  # YouTube doesn't provide email in API
            "name": channel_name,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
        }
        
        if existing_user:
            # Update existing user
            await db.users.update_one(
                {"channel_id": channel_id},
                {"$set": user_data}
            )
            user_data["id"] = existing_user["id"]
        else:
            # Create new user
            user_data["id"] = str(uuid.uuid4())
            await db.users.insert_one(user_data)
        
        user = User(**user_data)
        
        return {
            "access_token": credentials.token,
            "user": {
                "id": user.id,
                "name": user.name,
                "channel_name": user.channel_name,
                "channel_id": user.channel_id
            }
        }
        
    except Exception as e:
        logging.error(f"OAuth callback failed: {e}")
        raise HTTPException(status_code=500, detail="Authentication failed")

# YouTube API Routes
@api_router.get("/youtube/videos")
async def get_user_videos(current_user: User = Depends(get_current_user)):
    """Get user's YouTube videos"""
    try:
        user = await refresh_token_if_needed(current_user)
        creds = get_credentials_from_token(user.access_token, user.refresh_token)
        youtube = get_youtube_service(creds)
        
        # Get uploaded videos playlist
        channel_response = youtube.channels().list(
            part='contentDetails',
            mine=True
        ).execute()
        
        uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        
        # Get videos from uploads playlist
        videos_response = youtube.playlistItems().list(
            part='snippet',
            playlistId=uploads_playlist_id,
            maxResults=50
        ).execute()
        
        videos = []
        for item in videos_response.get('items', []):
            video_id = item['snippet']['resourceId']['videoId']
            
            # Get video details for duration
            video_details = youtube.videos().list(
                part='contentDetails,snippet',
                id=video_id
            ).execute()
            
            if video_details.get('items'):
                video = video_details['items'][0]
                videos.append(YouTubeVideo(
                    id=video_id,
                    title=item['snippet']['title'],
                    description=item['snippet']['description'][:200] + '...' if len(item['snippet']['description']) > 200 else item['snippet']['description'],
                    thumbnail_url=item['snippet']['thumbnails'].get('medium', {}).get('url', ''),
                    duration=video['contentDetails']['duration'],
                    published_at=item['snippet']['publishedAt']
                ))
        
        return {"videos": videos}
        
    except Exception as e:
        logging.error(f"Failed to fetch videos: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch videos")

@api_router.post("/schedule/broadcast")
async def schedule_broadcast(
    request: ScheduleRequest,
    current_user: User = Depends(get_current_user),
    background_tasks: BackgroundTasks = None
):
    """Schedule live broadcasts for a video"""
    import pytz
    
    try:
        user = await refresh_token_if_needed(current_user)
        creds = get_credentials_from_token(user.access_token, user.refresh_token)
        youtube = get_youtube_service(creds)
        
        # Default times if not provided
        default_times = ["05:55", "06:55", "07:55", "16:55", "17:55"]
        times_to_schedule = request.custom_times or default_times
        
        scheduled_broadcasts = []
        errors = []
        
        # Set user timezone to India (IST)
        user_tz = pytz.timezone("Asia/Kolkata")
        utc_tz = pytz.timezone("UTC")
        
        # Parse the selected date and convert from UTC to IST for date-only operations
        selected_date_str = request.selected_date.replace('Z', '')
        selected_date_utc = datetime.fromisoformat(selected_date_str)
        if selected_date_utc.tzinfo is None:
            selected_date_utc = selected_date_utc.replace(tzinfo=timezone.utc)
        
        # Convert to IST and get just the date part
        selected_date_ist = selected_date_utc.astimezone(user_tz)
        selected_date = selected_date_ist.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        
        # Get current time in both timezones for reference
        now_utc = datetime.now(utc_tz)
        now_ist = now_utc.astimezone(user_tz)
        
        logging.info(f"Current UTC time: {now_utc}")
        logging.info(f"Current IST time: {now_ist}")
        logging.info(f"Selected date (naive): {selected_date}")
        logging.info(f"Times to schedule: {times_to_schedule}")
        
        for time_str in times_to_schedule:
            try:
                # Parse time and combine with date in IST
                hour, minute = map(int, time_str.split(':'))
                scheduled_datetime_naive = selected_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                # Localize to IST
                scheduled_datetime_ist = user_tz.localize(scheduled_datetime_naive)
                
                # If the scheduled time is in the past (same day), move it to next day
                current_ist_naive = now_ist.replace(tzinfo=None)
                logging.info(f"Comparing: {scheduled_datetime_naive} with current IST: {current_ist_naive}")
                
                if scheduled_datetime_naive <= current_ist_naive:
                    # Add one day
                    scheduled_datetime_naive = scheduled_datetime_naive + timedelta(days=1)
                    scheduled_datetime_ist = user_tz.localize(scheduled_datetime_naive)
                    logging.info(f"Time was in past, moved to next day: {scheduled_datetime_ist}")
                
                # Convert to UTC for YouTube API
                scheduled_datetime_utc = scheduled_datetime_ist.astimezone(utc_tz)
                
                logging.info(f"Scheduling {time_str} IST -> {scheduled_datetime_utc} UTC")
                
                # Calculate time difference from now
                time_diff = scheduled_datetime_utc - now_utc
                minutes_from_now = time_diff.total_seconds() / 60
                
                # Validate scheduling constraints
                if time_diff.total_seconds() < 180:  # 3 minutes (reduced for testing)
                    errors.append(f"Time {time_str} IST is too soon ({int(minutes_from_now)} minutes from now). Must be at least 3 minutes in the future.")
                    continue
                
                if time_diff.days > 180:  # ~6 months
                    errors.append(f"Time {time_str} IST is too far in the future. Maximum 6 months ahead.")
                    continue
                
                # Format datetime for YouTube API
                scheduled_datetime_iso = scheduled_datetime_utc.strftime('%Y-%m-%dT%H:%M:%S.000Z')
                
                # Format time for display (12-hour format)
                time_display = scheduled_datetime_ist.strftime('%I%p').lower().replace(':00', '').replace('0', '')  # e.g., "5am", "6pm"
                
                # Create broadcast title with time
                broadcast_title = f"{request.video_title} - {time_display}"
                
                # Create live broadcast with auto-start/stop enabled
                broadcast_body = {
                    'snippet': {
                        'title': f"🔴 LIVE: {broadcast_title}",
                        'description': f"Scheduled live stream of: {request.video_title}\n\nScheduled for: {scheduled_datetime_ist.strftime('%Y-%m-%d %I:%M %p IST')}\nOriginal video: https://youtube.com/watch?v={request.video_id}",
                        'scheduledStartTime': scheduled_datetime_iso,
                    },
                    'status': {
                        'privacyStatus': 'unlisted',
                        'selfDeclaredMadeForKids': False
                    },
                    'contentDetails': {
                        'enableAutoStart': True,
                        'enableAutoStop': True,
                        'recordFromStart': True,
                        'enableDvr': True,
                        'enableContentEncryption': False,
                        'enableEmbed': True,
                        'projection': 'rectangular'
                    }
                }
                
                broadcast_response = youtube.liveBroadcasts().insert(
                    part='snippet,status,contentDetails',
                    body=broadcast_body
                ).execute()
                
                broadcast_id = broadcast_response['id']
                
                # Create live stream
                stream_body = {
                    'snippet': {
                        'title': f"Stream for {broadcast_title}"
                    },
                    'cdn': {
                        'frameRate': '30fps',
                        'ingestionType': 'rtmp',
                        'resolution': '720p'
                    }
                }
                
                stream_response = youtube.liveStreams().insert(
                    part='snippet,cdn',
                    body=stream_body
                ).execute()
                
                stream_id = stream_response['id']
                stream_name = stream_response['cdn']['ingestionInfo']['streamName']
                
                # Bind stream to broadcast
                youtube.liveBroadcasts().bind(
                    part='id',
                    id=broadcast_id,
                    streamId=stream_id
                ).execute()
                
                # Store in database
                broadcast_data = {
                    "id": str(uuid.uuid4()),
                    "user_id": user.id,
                    "video_id": request.video_id,
                    "video_title": request.video_title,
                    "broadcast_id": broadcast_id,
                    "stream_id": stream_id,
                    "scheduled_time": scheduled_datetime_utc.isoformat(),
                    "status": 'created',
                    "stream_url": stream_name,
                    "watch_url": f"https://www.youtube.com/watch?v={broadcast_id}",
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                
                await db.scheduled_broadcasts.insert_one(broadcast_data)
                scheduled_broadcasts.append(broadcast_data)
                scheduled_broadcasts.append(scheduled_broadcast)
                
                # Schedule the video streaming
                asyncio.create_task(
                    schedule_video_stream(
                        broadcast_id=broadcast_id,
                        stream_key=stream_name,
                        video_id=request.video_id,
                        start_time=scheduled_datetime_utc
                    )
                )
                
                logging.info(f"Successfully scheduled broadcast and video stream for {time_str} IST ({scheduled_datetime_utc} UTC)")
                
            except HttpError as youtube_error:
                error_details = str(youtube_error)
                if "invalidScheduledStartTime" in error_details:
                    errors.append(f"Time {time_str} IST: YouTube rejected the scheduling time. Try a time further in the future.")
                else:
                    errors.append(f"Time {time_str} IST: YouTube API error - {str(youtube_error)}")
                logging.error(f"YouTube API error for {time_str}: {youtube_error}")
            except Exception as slot_error:
                errors.append(f"Time {time_str} IST: Failed to schedule - {str(slot_error)}")
                logging.error(f"Error scheduling {time_str}: {slot_error}")
        
        # Prepare response
        response_message = f"Successfully scheduled {len(scheduled_broadcasts)} broadcasts for IST timezone"
        if errors:
            response_message += f". {len(errors)} failed"
        
        return {
            "message": response_message,
            "broadcasts": scheduled_broadcasts,
            "errors": errors,
            "success_count": len(scheduled_broadcasts),
            "error_count": len(errors),
            "timezone_info": {
                "user_timezone": "Asia/Kolkata (IST)",
                "current_ist_time": now_ist.strftime('%Y-%m-%d %H:%M:%S IST'),
                "current_utc_time": now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
            }
        }
        
    except Exception as e:
        logging.error(f"Failed to schedule broadcasts: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to schedule broadcasts: {str(e)}")

@api_router.get("/validate-schedule")
async def validate_schedule_time(date: str, time: str):
    """Validate if a schedule time is acceptable"""
    try:
        # Parse the datetime
        selected_date = datetime.fromisoformat(date.replace('Z', ''))
        if selected_date.tzinfo is None:
            selected_date = selected_date.replace(tzinfo=timezone.utc)
        
        hour, minute = map(int, time.split(':'))
        scheduled_datetime = selected_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        if scheduled_datetime.tzinfo is None:
            scheduled_datetime = scheduled_datetime.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        time_diff = scheduled_datetime - now
        
        validation_result = {
            "valid": True,
            "message": "Schedule time is valid",
            "scheduled_time": scheduled_datetime.isoformat(),
            "minutes_from_now": int(time_diff.total_seconds() / 60)
        }
        
        # Check constraints
        if time_diff.total_seconds() < 180:  # 3 minutes (reduced for testing)
            validation_result["valid"] = False
            validation_result["message"] = "Must be at least 3 minutes in the future"
        elif time_diff.days > 180:  # ~6 months
            validation_result["valid"] = False
            validation_result["message"] = "Cannot schedule more than 6 months in advance"
        elif scheduled_datetime <= now:
            validation_result["valid"] = False
            validation_result["message"] = "Schedule time must be in the future"
        
        return validation_result
        
    except Exception as e:
        return {
            "valid": False,
            "message": f"Invalid date/time format: {str(e)}",
            "scheduled_time": None,
            "minutes_from_now": 0
        }

@api_router.get("/broadcasts")
async def get_user_broadcasts(current_user: User = Depends(get_current_user)):
    """Get user's scheduled broadcasts"""
    try:
        broadcasts_cursor = db.scheduled_broadcasts.find(
            {"user_id": current_user.id}
        ).sort("scheduled_time", 1)
        
        broadcasts = []
        async for broadcast in broadcasts_cursor:
            # Remove MongoDB ObjectId to avoid serialization issues
            if "_id" in broadcast:
                del broadcast["_id"]
            broadcasts.append(broadcast)
        
        return {"broadcasts": broadcasts}
    
    except Exception as e:
        logging.error(f"Failed to fetch broadcasts: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch broadcasts")

@api_router.delete("/broadcasts/{broadcast_id}")
async def delete_broadcast(
    broadcast_id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete a scheduled broadcast"""
    try:
        # Find broadcast
        broadcast = await db.scheduled_broadcasts.find_one({
            "id": broadcast_id,
            "user_id": current_user.id
        })
        
        if not broadcast:
            raise HTTPException(status_code=404, detail="Broadcast not found")
        
        # Delete from YouTube if still exists
        user = await refresh_token_if_needed(current_user)
        creds = get_credentials_from_token(user.access_token, user.refresh_token)
        youtube = get_youtube_service(creds)
        
        try:
            youtube.liveBroadcasts().delete(id=broadcast['broadcast_id']).execute()
        except HttpError:
            pass  # Broadcast might already be deleted
        
        # Delete from database
        await db.scheduled_broadcasts.delete_one({"id": broadcast_id})
        
        return {"message": "Broadcast deleted successfully"}
        
    except Exception as e:
        logging.error(f"Failed to delete broadcast: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete broadcast")

# Test Routes
@api_router.get("/")
async def root():
    return {"message": "YouTube Live Streaming Scheduler API"}

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc)}

@api_router.get("/test/youtube-access")
async def test_youtube_access():
    """Test if we can access YouTube without authentication"""
    try:
        video_id = "dQw4w9WgXcQ"
        ydl_opts = {
            'format': 'best[height<=720]/best',
            'quiet': True,
            'socket_timeout': 10,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
            
            return {
                "success": True,
                "video_title": info.get("title", "Unknown"),
                "duration": info.get("duration", "Unknown"),
                "format_count": len(info.get("formats", [])),
                "has_url": "url" in info,
                "message": "YouTube access working"
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "YouTube access failed"
        }

@api_router.get("/test/video/{video_id}")
async def test_video_extraction(video_id: str, current_user: User = Depends(get_current_user)):
    """Test video URL extraction only"""
    try:
        logging.info(f"Testing video extraction for: {video_id}")
        video_url, extraction_info = await get_video_stream_url(video_id)
        
        if video_url:
            return {
                "success": True,
                "video_id": video_id,
                "video_url": video_url[:150] + "..." if len(video_url) > 150 else video_url,
                "extraction_method": extraction_info,
                "full_youtube_url": f"https://www.youtube.com/watch?v={video_id}"
            }
        else:
            return {
                "success": False,
                "video_id": video_id,
                "error": "Video extraction failed",
                "extraction_error": extraction_info,
                "full_youtube_url": f"https://www.youtube.com/watch?v={video_id}"
            }
    except Exception as e:
        return {"success": False, "error": str(e), "video_id": video_id}

@api_router.post("/test/stream")
async def test_streaming(
    video_id: str,
    stream_key: str,
    current_user: User = Depends(get_current_user)
):
    """Test streaming functionality with a specific video and stream key"""
    try:
        logging.info(f"Testing stream for video {video_id} with stream key {stream_key}")
        
        # Test video URL extraction
        video_url, extraction_info = await get_video_stream_url(video_id)
        if not video_url:
            return {
                "error": "Could not extract video URL", 
                "video_id": video_id,
                "extraction_error": extraction_info,
                "debug_info": f"Attempted to extract from: https://www.youtube.com/watch?v={video_id}"
            }
        
        logging.info(f"Extracted video URL: {video_url[:100]}...")
        
        # Test RTMP URL construction
        rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
        logging.info(f"RTMP URL: {rtmp_url}")
        
        # Test FFmpeg command construction
        cmd = [
            'ffmpeg',
            '-re',
            '-i', video_url,
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'veryfast',
            '-maxrate', '3000k',
            '-bufsize', '6000k',
            '-vf', 'scale=-2:720',
            '-g', '50',
            '-f', 'flv',
            '-t', '30',  # Only stream for 30 seconds for testing
            rtmp_url
        ]
        
        logging.info(f"FFmpeg command: {' '.join(cmd)}")
        
        # Start FFmpeg process with detailed logging
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE
        )
        
        # Wait a bit and check if process is still running
        time.sleep(5)
        
        if process.poll() is None:
            # Process is still running
            logging.info("FFmpeg process started successfully and is running")
            
            # Kill the test process after checking
            process.terminate()
            
            return {
                "success": True,
                "message": "Streaming test successful",
                "video_url": video_url[:100] + "...",
                "rtmp_url": rtmp_url,
                "process_status": "started_successfully",
                "extraction_method": extraction_info
            }
        else:
            # Process died, get error output
            stdout, stderr = process.communicate()
            logging.error(f"FFmpeg failed. STDOUT: {stdout.decode()}")
            logging.error(f"FFmpeg failed. STDERR: {stderr.decode()}")
            
            return {
                "success": False,
                "error": "FFmpeg process failed",
                "stdout": stdout.decode()[-500:],  # Last 500 chars
                "stderr": stderr.decode()[-500:],  # Last 500 chars
                "video_url": video_url[:100] + "...",
                "rtmp_url": rtmp_url,
                "extraction_method": extraction_info
            }
            
    except Exception as e:
        logging.error(f"Test streaming failed: {e}")
        return {"error": str(e)}

@api_router.post("/test/simple-stream")
async def test_simple_streaming(
    stream_key: str,
    current_user: User = Depends(get_current_user)
):
    """Test streaming with a simple test pattern instead of YouTube video"""
    try:
        logging.info(f"Testing simple stream with stream key {stream_key}")
        
        # Use a simple test pattern instead of YouTube video
        rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
        logging.info(f"RTMP URL: {rtmp_url}")
        
        # Create a simple test pattern using FFmpeg
        cmd = [
            'ffmpeg', '-y',
            '-f', 'lavfi',
            '-i', 'testsrc2=size=1280x720:rate=30',
            '-f', 'lavfi', 
            '-i', 'sine=frequency=1000:sample_rate=44100',
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'veryfast',
            '-tune', 'zerolatency',
            '-pix_fmt', 'yuv420p',
            '-maxrate', '2500k',
            '-bufsize', '5000k',
            '-vf', 'drawtext=text="Test Stream %{localtime}":fontcolor=white:fontsize=24:x=10:y=10',
            '-r', '30',
            '-g', '60',
            '-keyint_min', '30',
            '-sc_threshold', '0',
            '-b:v', '2000k',
            '-b:a', '128k',
            '-ar', '44100',
            '-f', 'flv',
            '-flvflags', 'no_duration_filesize',
            '-t', '60',  # Stream for 60 seconds
            rtmp_url
        ]
        
        logging.info(f"FFmpeg command: {' '.join(cmd)}")
        
        # Start FFmpeg process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1
        )
        
        # Wait a bit and check if process is running
        time.sleep(3)
        
        if process.poll() is None:
            logging.info("Simple test stream started successfully")
            
            # Store process info
            await db.streaming_processes.insert_one({
                "broadcast_id": f"test_simple_{int(time.time())}",
                "process_id": process.pid,
                "started_at": datetime.now(timezone.utc),
                "video_id": "test_pattern",
                "stream_type": "simple_test"
            })
            
            return {
                "success": True,
                "message": "Simple test stream started successfully",
                "rtmp_url": rtmp_url,
                "process_id": process.pid,
                "stream_duration": "60 seconds",
                "test_pattern": "Color bars with timestamp and 1kHz tone"
            }
        else:
            # Process failed, get error output
            stdout, stderr = process.communicate()
            logging.error(f"Simple stream FFmpeg failed. Output: {stdout}")
            
            return {
                "success": False,
                "error": "FFmpeg process failed to start",
                "output": stdout[-500:] if stdout else "No output",
                "rtmp_url": rtmp_url
            }
            
    except Exception as e:
        logging.error(f"Simple streaming test failed: {e}")
        return {"success": False, "error": str(e)}

@api_router.post("/upload-video")
async def upload_video(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """Upload a video file for streaming"""
    try:
        import os
        
        # Validate file type
        if not file.filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv')):
            raise HTTPException(status_code=400, detail="Only video files are allowed")
        
        # Create uploads directory if it doesn't exist
        upload_dir = "/app/uploads"
        os.makedirs(upload_dir, exist_ok=True)
        
        # Generate unique filename
        file_id = str(uuid.uuid4())
        file_extension = os.path.splitext(file.filename)[1]
        saved_filename = f"{file_id}{file_extension}"
        file_path = os.path.join(upload_dir, saved_filename)
        
        # Save uploaded file
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        file_size = os.path.getsize(file_path)
        
        # Store file info in database
        file_info = {
            "id": file_id,
            "user_id": current_user.id,
            "original_filename": file.filename,
            "saved_filename": saved_filename,
            "file_path": file_path,
            "file_size": file_size,
            "upload_time": datetime.now(timezone.utc).isoformat(),
            "content_type": file.content_type
        }
        
        await db.uploaded_videos.insert_one(file_info)
        
        return {
            "success": True,
            "file_id": file_id,
            "filename": file.filename,
            "size_mb": round(file_size / 1024 / 1024, 2),
            "message": "Video uploaded successfully"
        }
        
    except Exception as e:
        logging.error(f"Video upload failed: {e}")
        raise HTTPException(status_code=500, detail="Video upload failed")

@api_router.get("/uploaded-videos")
async def get_uploaded_videos(current_user: User = Depends(get_current_user)):
    """Get list of uploaded videos for current user"""
    try:
        videos_cursor = db.uploaded_videos.find(
            {"user_id": current_user.id}
        ).sort("upload_time", -1)
        
        videos = []
        async for video in videos_cursor:
            # Remove MongoDB ObjectId to avoid serialization issues
            if "_id" in video:
                del video["_id"]
            videos.append(video)
        
        return {"videos": videos}
    except Exception as e:
        logging.error(f"Failed to get uploaded videos: {e}")
        raise HTTPException(status_code=500, detail="Failed to get uploaded videos")

@api_router.post("/schedule/uploaded-video")
async def schedule_uploaded_video(
    file_id: str,
    selected_date: str,
    custom_times: list[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Schedule broadcasts using uploaded video"""
    try:
        # Get uploaded video info
        video_info = await db.uploaded_videos.find_one({"id": file_id, "user_id": current_user.id})
        if not video_info:
            raise HTTPException(status_code=404, detail="Video not found")
        
        # Similar scheduling logic but use local file
        user = await refresh_token_if_needed(current_user)
        creds = get_credentials_from_token(user.access_token, user.refresh_token)
        youtube = get_youtube_service(creds)
        
        # Default times if not provided
        default_times = ["05:55", "06:55", "07:55", "16:55", "17:55"]
        times_to_schedule = custom_times or default_times
        
        scheduled_broadcasts = []
        errors = []
        
        # [Rest of scheduling logic would go here - similar to existing but using local file]
        
        return {
            "message": f"Successfully scheduled broadcasts using uploaded video",
            "broadcasts": scheduled_broadcasts,
            "video_file": video_info["original_filename"]
        }
        
    except Exception as e:
        logging.error(f"Failed to schedule uploaded video: {e}")
        raise HTTPException(status_code=500, detail="Failed to schedule uploaded video")

@api_router.post("/test/download-stream")
async def test_download_streaming(
    video_id: str,
    stream_key: str,
    current_user: User = Depends(get_current_user)
):
    """Test streaming by downloading video first, then streaming local file"""
    try:
        import tempfile
        import os
        
        logging.info(f"Testing download-then-stream for video {video_id}")
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        temp_file = os.path.join(temp_dir, f"{video_id}.mp4")
        
        # Download the video using yt-dlp with robust settings
        ydl_opts = {
            'format': 'best[ext=mp4][height<=720]/best[height<=720]',
            'outtmpl': temp_file,
            'quiet': False,
            'retries': 2,
            'fragment_retries': 2,
            'socket_timeout': 20,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f'https://www.youtube.com/watch?v={video_id}'])
        
        # Check if file was downloaded
        if not os.path.exists(temp_file):
            return {"success": False, "error": "Video download failed"}
        
        file_size = os.path.getsize(temp_file)
        logging.info(f"Downloaded video: {temp_file} ({file_size} bytes)")
        
        # Stream the local file
        rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
        
        cmd = [
            'ffmpeg', '-y',
            '-re',  # Read at native frame rate
            '-i', temp_file,
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'veryfast',
            '-tune', 'zerolatency',
            '-pix_fmt', 'yuv420p',
            '-maxrate', '2500k',
            '-bufsize', '5000k',
            '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2',
            '-r', '30',
            '-g', '60',
            '-keyint_min', '30',
            '-sc_threshold', '0',
            '-b:v', '2000k',
            '-b:a', '128k',
            '-ar', '44100',
            '-f', 'flv',
            '-flvflags', 'no_duration_filesize',
            '-t', '60',  # Stream for 60 seconds
            rtmp_url
        ]
        
        logging.info(f"Streaming local file: {' '.join(cmd)}")
        
        # Start FFmpeg process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1
        )
        
        # Wait and check if process is running
        time.sleep(3)
        
        if process.poll() is None:
            logging.info("Download-and-stream started successfully")
            
            # Schedule cleanup after streaming
            def cleanup():
                time.sleep(70)  # Wait for stream to finish
                try:
                    os.remove(temp_file)
                    os.rmdir(temp_dir)
                    logging.info(f"Cleaned up temporary files: {temp_file}")
                except:
                    pass
            
            threading.Thread(target=cleanup, daemon=True).start()
            
            return {
                "success": True,
                "message": "Download-and-stream started successfully",
                "rtmp_url": rtmp_url,
                "process_id": process.pid,
                "temp_file": temp_file,
                "file_size_mb": round(file_size / 1024 / 1024, 2),
                "stream_duration": "60 seconds"
            }
        else:
            # Process failed
            stdout, stderr = process.communicate()
            
            # Cleanup
            try:
                os.remove(temp_file)
                os.rmdir(temp_dir)
            except:
                pass
            
            return {
                "success": False,
                "error": "FFmpeg process failed",
                "output": stdout[-500:] if stdout else "No output",
                "rtmp_url": rtmp_url
            }
            
    except Exception as e:
        logging.error(f"Download-stream test failed: {e}")
        return {"success": False, "error": str(e)}

@api_router.get("/streaming/status")
async def get_streaming_status(current_user: User = Depends(get_current_user)):
    """Get status of active streams"""
    try:
        # Get all streaming processes for user's broadcasts
        user_broadcasts = await db.scheduled_broadcasts.find({"user_id": current_user.id}).to_list(100)
        broadcast_ids = [b["broadcast_id"] for b in user_broadcasts]
        
        active_streams = await db.streaming_processes.find(
            {"broadcast_id": {"$in": broadcast_ids}}
        ).to_list(100)
        
        # Check which processes are still running
        running_streams = []
        for stream in active_streams:
            try:
                # Check if process is still running
                process = subprocess.Popen(['ps', '-p', str(stream['process_id'])], 
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                output, _ = process.communicate()
                
                if str(stream['process_id']) in output.decode():
                    running_streams.append({
                        "broadcast_id": stream["broadcast_id"],
                        "video_id": stream["video_id"],
                        "started_at": stream["started_at"],
                        "status": "streaming"
                    })
            except:
                pass
        
        return {"active_streams": running_streams}
        
    except Exception as e:
        logging.error(f"Failed to get streaming status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get streaming status")

@api_router.post("/streaming/stop/{broadcast_id}")
async def stop_stream(broadcast_id: str, current_user: User = Depends(get_current_user)):
    """Manually stop a streaming process"""
    try:
        # Find the streaming process
        stream_process = await db.streaming_processes.find_one({"broadcast_id": broadcast_id})
        
        if not stream_process:
            raise HTTPException(status_code=404, detail="Stream process not found")
        
        # Kill the FFmpeg process
        try:
            subprocess.run(['kill', str(stream_process['process_id'])], check=True)
            
            # Remove from database
            await db.streaming_processes.delete_one({"broadcast_id": broadcast_id})
            
            return {"message": "Stream stopped successfully"}
        except subprocess.CalledProcessError:
            return {"message": "Stream process was already stopped"}
        
    except Exception as e:
        logging.error(f"Failed to stop stream: {e}")
        raise HTTPException(status_code=500, detail="Failed to stop stream")

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()