from fastapi import FastAPI, APIRouter, HTTPException, Depends, BackgroundTasks, status
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
            'format': 'best[height<=720][ext=mp4]/best[height<=720]/best[ext=mp4]/best',
            'quiet': False,  # Enable verbose output for debugging
            'no_warnings': False,
            'extractaudio': False,
            'audioformat': 'aac',
            'outtmpl': '%(id)s.%(ext)s',
            'writesubtitles': False,
            'writeautomaticsub': False,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
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
                    
                    # Try to find a good format with both video and audio
                    for fmt in formats:
                        if (fmt.get('vcodec') != 'none' and 
                            fmt.get('acodec') != 'none' and 
                            fmt.get('url') and
                            fmt.get('height', 0) <= 720):
                            stream_url = fmt['url']
                            extraction_method = f"format_selection_height_{fmt.get('height', 'unknown')}"
                            logging.info(f"Selected format: {fmt.get('format_id')} - {fmt.get('height', 'unknown')}p")
                            break
                    
                    # Fallback: any format with URL
                    if not stream_url:
                        for fmt in formats:
                            if fmt.get('url'):
                                stream_url = fmt['url']
                                extraction_method = f"fallback_format_{fmt.get('format_id', 'unknown')}"
                                logging.info(f"Using fallback format: {fmt.get('format_id')}")
                                break
                
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
                error_msg = f"yt-dlp download error: {str(e)}"
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
        # FFmpeg command to stream video to RTMP
        cmd = [
            'ffmpeg',
            '-re',  # Read input at native frame rate
            '-i', video_url,  # Input video URL
            '-c:v', 'libx264',  # Video codec
            '-c:a', 'aac',  # Audio codec
            '-preset', 'ultrafast',  # Faster encoding preset
            '-tune', 'zerolatency',  # Low latency tuning
            '-maxrate', '2500k',  # Lower maximum bitrate
            '-bufsize', '5000k',  # Buffer size
            '-vf', 'scale=1280:720',  # Fixed scale to 720p
            '-r', '30',  # Frame rate
            '-g', '60',  # GOP size
            '-keyint_min', '60',  # Minimum GOP size
            '-sc_threshold', '0',  # Disable scene change detection
            '-f', 'flv',  # Output format
            '-flvflags', 'no_duration_filesize',  # FLV flags for live streaming
            rtmp_url  # RTMP destination
        ]
        
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
    try:
        # Calculate wait time
        now = datetime.now(timezone.utc)
        wait_seconds = (start_time - now).total_seconds()
        
        if wait_seconds > 0:
            logging.info(f"Waiting {wait_seconds} seconds to start stream for broadcast {broadcast_id}")
            await asyncio.sleep(wait_seconds)
        
        # Get video stream URL
        video_url = await get_video_stream_url(video_id)
        if not video_url:
            logging.error(f"Could not get video URL for {video_id}")
            return
        
        # Construct RTMP URL
        rtmp_url = f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
        
        # Start streaming
        logging.info(f"Starting stream for broadcast {broadcast_id}")
        process = stream_video_to_rtmp(video_url, rtmp_url)
        
        if process:
            # Store process info for potential cleanup
            await db.streaming_processes.insert_one({
                "broadcast_id": broadcast_id,
                "process_id": process.pid,
                "started_at": datetime.now(timezone.utc),
                "video_id": video_id
            })
            
            logging.info(f"Stream started successfully for broadcast {broadcast_id}")
        else:
            logging.error(f"Failed to start stream for broadcast {broadcast_id}")
            
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
        
        # Parse the selected date (assume user local date)
        selected_date_str = request.selected_date.replace('Z', '')
        selected_date = datetime.fromisoformat(selected_date_str)
        if selected_date.tzinfo is not None:
            selected_date = selected_date.replace(tzinfo=None)
        
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
                scheduled_broadcast = ScheduledBroadcast(
                    user_id=user.id,
                    video_id=request.video_id,
                    video_title=request.video_title,
                    broadcast_id=broadcast_id,
                    stream_id=stream_id,
                    scheduled_time=scheduled_datetime_utc,  # Store UTC time
                    status='created',
                    stream_url=stream_name,
                    watch_url=f"https://www.youtube.com/watch?v={broadcast_id}"
                )
                
                await db.scheduled_broadcasts.insert_one(scheduled_broadcast.dict())
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
        broadcasts = await db.scheduled_broadcasts.find(
            {"user_id": current_user.id}
        ).sort("scheduled_time", 1).to_list(100)
        
        return {"broadcasts": [ScheduledBroadcast(**broadcast) for broadcast in broadcasts]}
    
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
        video_url = await get_video_stream_url(video_id)
        if not video_url:
            return {"error": "Could not extract video URL", "video_id": video_id}
        
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
                "process_status": "started_successfully"
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
                "rtmp_url": rtmp_url
            }
            
    except Exception as e:
        logging.error(f"Test streaming failed: {e}")
        return {"error": str(e)}

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