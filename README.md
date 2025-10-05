# YouTube Live Streaming Scheduler

A professional YouTube Live streaming scheduler that allows you to upload videos and schedule them for automatic live streaming at specific times.

## Features

- 🔐 **Password Protection**: Secure access with custom password
- 📹 **Video Upload**: Upload videos up to 2GB with progress tracking
- ⏰ **Smart Scheduling**: Schedule broadcasts for 5 default IST times or custom times
- 🎯 **Auto-streaming**: Automatic FFmpeg streaming to YouTube Live
- ✏️ **Video Management**: Edit titles, delete videos, manage uploads
- 📊 **Progress Tracking**: Real-time upload progress with speed and time estimates
- 🔄 **24/7 Operation**: Designed for continuous server operation

## Quick Deploy on Hetzner

### 1. Server Setup
```bash
# Create Hetzner server (CPX21 recommended)
# Point live.happyfying.com to server IP

# Connect to server
ssh root@YOUR_SERVER_IP

# Clone repository
git clone https://github.com/YOUR_USERNAME/youtube-live-scheduler.git
cd youtube-live-scheduler
```

### 2. Install Dependencies
```bash
# Make deploy script executable
chmod +x deploy.sh
./deploy.sh
```

### 3. SSL Certificate
```bash
# Get SSL certificate for your domain
certbot certonly --standalone -d live.happyfying.com
```

### 4. Deploy Application
```bash
# Start all services
docker-compose up -d

# Check status
docker-compose ps
```

### 5. Update Google OAuth
- Add `https://live.happyfying.com/auth/callback` to your Google Cloud Console OAuth settings

## Configuration

### Environment Variables
- **Backend**: MONGO_URL, DB_NAME, CORS_ORIGINS
- **Frontend**: REACT_APP_BACKEND_URL

### Default Settings
- **Password**: `Jaigurudev123@`
- **Default Times**: 5:55 AM, 6:55 AM, 7:55 AM, 4:55 PM, 5:55 PM (IST)
- **Upload Limit**: 2GB per file
- **Timezone**: India Standard Time (IST)

## Architecture

- **Backend**: FastAPI + Python + FFmpeg
- **Frontend**: React + Tailwind CSS + Shadcn UI
- **Database**: MongoDB
- **Deployment**: Docker + Docker Compose + Nginx
- **SSL**: Let's Encrypt (Certbot)

## Costs (Hetzner)
- **CPX21 Server**: €4.15/month (~₹375/month)
- **Domain**: Your own (live.happyfying.com)
- **SSL**: Free (Let's Encrypt)
