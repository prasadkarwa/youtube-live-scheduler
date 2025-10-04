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
    try:
        user = await refresh_token_if_needed(current_user)
        creds = get_credentials_from_token(user.access_token, user.refresh_token)
        youtube = get_youtube_service(creds)
        
        # Default times if not provided
        default_times = ["05:55", "06:55", "07:55", "16:55", "17:55"]
        times_to_schedule = request.custom_times or default_times
        
        scheduled_broadcasts = []
        errors = []
        
        # Parse the selected date (ensure it's treated as UTC)
        selected_date = datetime.fromisoformat(request.selected_date.replace('Z', ''))
        if selected_date.tzinfo is None:
            selected_date = selected_date.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        
        for time_str in times_to_schedule:
            try:
                # Parse time and combine with date
                hour, minute = map(int, time_str.split(':'))
                scheduled_datetime = selected_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                # Ensure timezone is set
                if scheduled_datetime.tzinfo is None:
                    scheduled_datetime = scheduled_datetime.replace(tzinfo=timezone.utc)
                
                # Validate scheduling constraints
                time_diff = scheduled_datetime - now
                
                # YouTube requires at least 15 minutes in the future
                if time_diff.total_seconds() < 900:  # 15 minutes
                    errors.append(f"Time {time_str} is too soon. Must be at least 15 minutes in the future.")
                    continue
                
                # YouTube doesn't allow scheduling more than 6 months in advance
                if time_diff.days > 180:  # ~6 months
                    errors.append(f"Time {time_str} is too far in the future. Maximum 6 months ahead.")
                    continue
                
                # Format datetime for YouTube API (ISO format with Z suffix)
                scheduled_datetime_iso = scheduled_datetime.strftime('%Y-%m-%dT%H:%M:%S.000Z')
                
                # Create live broadcast
                broadcast_body = {
                    'snippet': {
                        'title': f"🔴 LIVE: {request.video_title}",
                        'description': f"Scheduled live stream of: {request.video_title}\n\nOriginal video: https://youtube.com/watch?v={request.video_id}",
                        'scheduledStartTime': scheduled_datetime_iso,
                    },
                    'status': {
                        'privacyStatus': 'unlisted',  # Set as unlisted by default
                        'selfDeclaredMadeForKids': False
                    }
                }
                
                broadcast_response = youtube.liveBroadcasts().insert(
                    part='snippet,status',
                    body=broadcast_body
                ).execute()
                
                broadcast_id = broadcast_response['id']
                
                # Create live stream
                stream_body = {
                    'snippet': {
                        'title': f"Stream for {request.video_title} at {time_str}"
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
                    scheduled_time=scheduled_datetime,
                    status='created',
                    stream_url=stream_name,
                    watch_url=f"https://www.youtube.com/watch?v={broadcast_id}"
                )
                
                await db.scheduled_broadcasts.insert_one(scheduled_broadcast.dict())
                scheduled_broadcasts.append(scheduled_broadcast)
                
            except HttpError as youtube_error:
                error_details = str(youtube_error)
                if "invalidScheduledStartTime" in error_details:
                    errors.append(f"Time {time_str}: Invalid scheduling time. YouTube requires broadcasts to be scheduled between 15 minutes and 6 months from now.")
                else:
                    errors.append(f"Time {time_str}: YouTube API error - {youtube_error}")
                logging.error(f"YouTube API error for time {time_str}: {youtube_error}")
            except Exception as slot_error:
                errors.append(f"Time {time_str}: Failed to schedule - {str(slot_error)}")
                logging.error(f"Error scheduling time {time_str}: {slot_error}")
        
        # Prepare response
        response_message = f"Successfully scheduled {len(scheduled_broadcasts)} broadcasts"
        if errors:
            response_message += f". {len(errors)} failed: " + "; ".join(errors)
        
        return {
            "message": response_message,
            "broadcasts": scheduled_broadcasts,
            "errors": errors,
            "success_count": len(scheduled_broadcasts),
            "error_count": len(errors)
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
        if time_diff.total_seconds() < 900:  # 15 minutes
            validation_result["valid"] = False
            validation_result["message"] = "Must be at least 15 minutes in the future"
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