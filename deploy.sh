#!/bin/bash

# YouTube Live Scheduler - Hetzner Deployment Script
# Run this script on your Hetzner server

set -e

echo "🚀 Starting YouTube Live Scheduler deployment..."

# Update system
echo "📦 Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install Docker and Docker Compose
echo "🐳 Installing Docker..."
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Install Docker Compose
echo "📝 Installing Docker Compose..."
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Install Certbot for SSL
echo "🔒 Installing Certbot..."
sudo apt install -y certbot python3-certbot-nginx

# Create application directory
echo "📁 Creating application directory..."
sudo mkdir -p /opt/youtube-scheduler
cd /opt/youtube-scheduler

echo "✅ Setup complete! Next steps:"
echo "1. Upload your application files to /opt/youtube-scheduler"
echo "2. Set up SSL certificate with: sudo certbot certonly --standalone -d live.happyfying.com"
echo "3. Run: docker-compose up -d"
echo "4. Your app will be available at https://live.happyfying.com"