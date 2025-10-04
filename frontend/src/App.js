import { useState, useEffect } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import axios from "axios";
import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { Badge } from "./components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "./components/ui/dialog";
import { Calendar } from "./components/ui/calendar";
import { toast } from "sonner";
import { Toaster } from "./components/ui/sonner";
import { Input } from "./components/ui/input";
import { Label } from "./components/ui/label";
import { AlertCircle, Calendar as CalendarIcon, Clock, Play, Trash2, Youtube, VideoIcon } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Auth component
const AuthPage = ({ onAuth }) => {
  const [loading, setLoading] = useState(false);

  const handleGoogleAuth = async () => {
    setLoading(true);
    try {
      const response = await axios.get(`${API}/auth/url`);
      window.location.href = response.data.auth_url;
    } catch (error) {
      console.error('Auth failed:', error);
      toast.error('Failed to initiate Google authentication');
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-red-50 to-pink-50 flex items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center space-y-4">
          <div className="mx-auto w-16 h-16 bg-red-100 rounded-full flex items-center justify-center">
            <Youtube className="w-8 h-8 text-red-600" />
          </div>
          <div>
            <CardTitle className="text-2xl font-bold text-gray-900">YouTube Live Scheduler</CardTitle>
            <p className="text-gray-600 mt-2">Schedule your videos as live streams with automated timing</p>
          </div>
        </CardHeader>
        <CardContent>
          <Button 
            onClick={handleGoogleAuth} 
            disabled={loading}
            className="w-full bg-red-600 hover:bg-red-700 text-white py-3"
            data-testid="google-auth-button"
          >
            {loading ? (
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                Connecting...
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Youtube className="w-5 h-5" />
                Connect YouTube Channel
              </div>
            )}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
};

// Video selection component
const VideoSelector = ({ videos, onVideoSelect, selectedVideo }) => {
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-900">Select a video to schedule</h3>
      <div className="grid gap-4 max-h-96 overflow-y-auto">
        {videos.map((video) => (
          <Card 
            key={video.id} 
            className={`cursor-pointer transition-all hover:shadow-md ${
              selectedVideo?.id === video.id ? 'ring-2 ring-red-500 bg-red-50' : ''
            }`}
            onClick={() => onVideoSelect(video)}
            data-testid={`video-card-${video.id}`}
          >
            <CardContent className="p-4">
              <div className="flex gap-4">
                <img 
                  src={video.thumbnail_url} 
                  alt={video.title}
                  className="w-32 h-20 object-cover rounded-lg flex-shrink-0"
                />
                <div className="flex-1 min-w-0">
                  <h4 className="font-medium text-gray-900 truncate">{video.title}</h4>
                  <p className="text-sm text-gray-600 mt-1 line-clamp-2">{video.description}</p>
                  <div className="flex items-center gap-2 mt-2">
                    <Badge variant="secondary" className="text-xs">
                      {new Date(video.published_at).toLocaleDateString()}
                    </Badge>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
};

// Scheduling component
const ScheduleForm = ({ selectedVideo, onSchedule, loading }) => {
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [customTimes, setCustomTimes] = useState(['05:55', '06:55', '07:55', '16:55', '17:55']);
  const [showCustomTimes, setShowCustomTimes] = useState(false);
  const [validationErrors, setValidationErrors] = useState([]);

  const validateScheduleTimes = () => {
    const errors = [];
    
    // Get current time in IST - use proper IST calculation
    const now = new Date();
    const nowIST = new Date(now.toLocaleString("en-US", {timeZone: "Asia/Kolkata"}));
    
    const times = showCustomTimes ? customTimes : ['05:55', '06:55', '07:55', '16:55', '17:55'];
    
    // Check if selected date is in the past (IST date)
    const todayIST = new Date(nowIST.getFullYear(), nowIST.getMonth(), nowIST.getDate());
    const selectedDateOnly = new Date(selectedDate.getFullYear(), selectedDate.getMonth(), selectedDate.getDate());
    
    if (selectedDateOnly < todayIST) {
      errors.push('Selected date cannot be in the past (IST timezone)');
      return errors;
    }

    times.forEach((timeStr, index) => {
      const [hour, minute] = timeStr.split(':').map(Number);
      
      // Create schedule time for selected date
      let scheduleDateTime = new Date(selectedDate);
      scheduleDateTime.setHours(hour, minute, 0, 0);
      
      // If scheduling for today and time is in the past, assume next day
      const isToday = selectedDateOnly.getTime() === todayIST.getTime();
      if (isToday && scheduleDateTime <= nowIST) {
        scheduleDateTime = new Date(scheduleDateTime.getTime() + 24 * 60 * 60 * 1000); // Add one day
      }
      
      // Calculate time difference
      const timeDiff = scheduleDateTime - nowIST;
      const minutesFromNow = timeDiff / (1000 * 60);

      if (minutesFromNow < 3) {
        errors.push(`Time ${timeStr} IST: Must be at least 3 minutes in the future (${Math.round(minutesFromNow)} mins from now)`);
      }

      if (timeDiff > 180 * 24 * 60 * 60 * 1000) { // 180 days in milliseconds
        errors.push(`Time ${timeStr} IST: Cannot schedule more than 6 months in advance`);
      }
    });

    return errors;
  };

  const handleTimeChange = (index, value) => {
    const newTimes = [...customTimes];
    newTimes[index] = value;
    setCustomTimes(newTimes);
    setValidationErrors([]); // Clear validation errors when times change
  };

  const addTimeSlot = () => {
    setCustomTimes([...customTimes, '12:00']);
  };

  const removeTimeSlot = (index) => {
    setCustomTimes(customTimes.filter((_, i) => i !== index));
  };

  const handleDateChange = (date) => {
    setSelectedDate(date);
    setValidationErrors([]); // Clear validation errors when date changes
  };

  const handleSchedule = () => {
    if (!selectedVideo || !selectedDate) {
      toast.error('Please select a video and date');
      return;
    }

    // Validate schedule times
    const errors = validateScheduleTimes();
    if (errors.length > 0) {
      setValidationErrors(errors);
      toast.error(`Validation failed: ${errors[0]}`);
      return;
    }

    const scheduleData = {
      video_id: selectedVideo.id,
      video_title: selectedVideo.title,
      selected_date: selectedDate.toISOString(),
      custom_times: showCustomTimes ? customTimes : null,
      timezone: "Asia/Kolkata"
    };

    onSchedule(scheduleData);
  };

  if (!selectedVideo) {
    return (
      <div className="text-center py-8 text-gray-500">
        <VideoIcon className="w-12 h-12 mx-auto mb-4 text-gray-300" />
        <p>Select a video to start scheduling live streams</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="bg-blue-50 p-4 rounded-lg">
        <h4 className="font-medium text-blue-900 mb-2">Selected Video</h4>
        <p className="text-blue-800">{selectedVideo.title}</p>
      </div>

      <div className="space-y-4">
        <Label className="text-base font-medium">Select Date</Label>
        <Calendar
          mode="single"
          selected={selectedDate}
          onSelect={handleDateChange}
          disabled={(date) => {
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            return date < today || date > new Date(Date.now() + 180 * 24 * 60 * 60 * 1000); // 6 months max
          }}
          className="rounded-md border"
          data-testid="date-calendar"
        />
        <div className="space-y-1">
          <p className="text-sm text-gray-600">
            ⏰ Broadcasts can be scheduled 3 minutes to 6 months from now (IST timezone)
          </p>
          <p className="text-xs text-blue-600">
            🌍 Current IST time: {new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}
          </p>
          <p className="text-xs text-green-600">
            🔄 Auto-start and auto-stop are enabled for all scheduled broadcasts
          </p>
        </div>
      </div>

      {/* Validation Errors */}
      {validationErrors.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-start gap-2">
            <AlertCircle className="w-5 h-5 text-red-600 mt-0.5 flex-shrink-0" />
            <div>
              <h4 className="text-red-800 font-medium">Scheduling Issues</h4>
              <ul className="mt-2 text-sm text-red-700 space-y-1">
                {validationErrors.map((error, index) => (
                  <li key={index}>• {error}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Label className="text-base font-medium">Broadcast Times</Label>
          <Button
            variant="outline" 
            size="sm"
            onClick={() => setShowCustomTimes(!showCustomTimes)}
            data-testid="toggle-custom-times"
          >
            {showCustomTimes ? 'Use Default Times' : 'Customize Times'}
          </Button>
        </div>

        {!showCustomTimes && (
          <div className="bg-gray-50 p-4 rounded-lg">
            <p className="text-sm text-gray-600 mb-2">Default broadcast times (IST):</p>
            <div className="flex flex-wrap gap-2">
              {['05:55', '06:55', '07:55', '16:55', '17:55'].map((time, index) => (
                <Badge key={index} className="bg-red-100 text-red-800">{time} IST</Badge>
              ))}
            </div>
          </div>
        )}

        {showCustomTimes && (
          <div className="space-y-3">
            {customTimes.map((time, index) => (
              <div key={index} className="flex items-center gap-2">
                <Input
                  type="time"
                  value={time}
                  onChange={(e) => handleTimeChange(index, e.target.value)}
                  className="w-32"
                  data-testid={`time-input-${index}`}
                />
                {customTimes.length > 1 && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => removeTimeSlot(index)}
                    className="p-2"
                    data-testid={`remove-time-${index}`}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                )}
              </div>
            ))}
            <Button
              variant="outline"
              onClick={addTimeSlot}
              className="w-full"
              data-testid="add-time-slot"
            >
              Add Time Slot
            </Button>
          </div>
        )}
      </div>

      <Button 
        onClick={handleSchedule}
        disabled={loading}
        className="w-full bg-red-600 hover:bg-red-700 text-white"
        data-testid="schedule-broadcast-button"
      >
        {loading ? (
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
            Scheduling...
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <CalendarIcon className="w-4 h-4" />
            Schedule Live Broadcasts
          </div>
        )}
      </Button>
    </div>
  );
};

// Broadcasts list component
const BroadcastsList = ({ broadcasts, onDelete, loading }) => {
  const getBadgeVariant = (status) => {
    switch (status) {
      case 'created': return 'default';
      case 'streaming': return 'destructive';
      case 'completed': return 'secondary';
      case 'failed': return 'destructive';
      case 'scheduled': return 'default';
      default: return 'default';
    }
  };

  const isUpcoming = (scheduledTime) => {
    return new Date(scheduledTime) > new Date();
  };

  // Sort broadcasts: upcoming first, then completed/failed
  const sortedBroadcasts = [...broadcasts].sort((a, b) => {
    const aUpcoming = isUpcoming(a.scheduled_time);
    const bUpcoming = isUpcoming(b.scheduled_time);
    
    if (aUpcoming && !bUpcoming) return -1;
    if (!aUpcoming && bUpcoming) return 1;
    
    // Within same category, sort by scheduled time
    return new Date(a.scheduled_time) - new Date(b.scheduled_time);
  });

  const formatDateTime = (dateTime) => {
    return new Date(dateTime).toLocaleString('en-US', {
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Asia/Kolkata',
      timeZoneName: 'short'
    });
  };

  if (!broadcasts || broadcasts.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500">
        <Clock className="w-12 h-12 mx-auto mb-4 text-gray-300" />
        <p>No scheduled broadcasts yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-900">Scheduled Broadcasts</h3>
      <div className="space-y-3">
        {sortedBroadcasts.map((broadcast) => {
          const upcoming = isUpcoming(broadcast.scheduled_time);
          return (
          <Card 
            key={broadcast.id} 
            data-testid={`broadcast-card-${broadcast.id}`}
            className={upcoming ? '' : 'opacity-70 border-gray-200'}
          >
            <CardContent className="p-4">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <h4 className="font-medium text-gray-900 mb-1">{broadcast.video_title}</h4>
                  <div className="flex items-center gap-4 text-sm text-gray-600">
                    <div className="flex items-center gap-1">
                      <CalendarIcon className="w-4 h-4" />
                      {formatDateTime(broadcast.scheduled_time)}
                    </div>
                    <Badge variant={getBadgeVariant(broadcast.status)}>
                      {broadcast.status}
                    </Badge>
                  </div>
                  <div className="mt-2 flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => window.open(broadcast.watch_url, '_blank')}
                      data-testid={`watch-button-${broadcast.id}`}
                    >
                      <Play className="w-4 h-4 mr-1" />
                      Watch Page
                    </Button>
                    <div className="text-xs text-gray-500 flex items-center">
                      📺 Auto-stream enabled
                    </div>
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onDelete(broadcast.id)}
                  disabled={loading}
                  className="ml-2 text-red-600 hover:text-red-700"
                  data-testid={`delete-button-${broadcast.id}`}
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
};

// Main dashboard component
const Dashboard = ({ user, onLogout }) => {
  const [videos, setVideos] = useState([]);
  const [broadcasts, setBroadcasts] = useState([]);
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [fetchingVideos, setFetchingVideos] = useState(true);
  const [fetchingBroadcasts, setFetchingBroadcasts] = useState(true);

  useEffect(() => {
    fetchVideos();
    fetchBroadcasts();
  }, []);

  const fetchVideos = async () => {
    try {
      const response = await axios.get(`${API}/youtube/videos`, {
        headers: { Authorization: `Bearer ${user.access_token}` }
      });
      setVideos(response.data.videos || []);
    } catch (error) {
      console.error('Failed to fetch videos:', error);
      toast.error('Failed to load your videos');
    } finally {
      setFetchingVideos(false);
    }
  };

  const fetchBroadcasts = async () => {
    try {
      const response = await axios.get(`${API}/broadcasts`, {
        headers: { Authorization: `Bearer ${user.access_token}` }
      });
      setBroadcasts(response.data.broadcasts || []);
    } catch (error) {
      console.error('Failed to fetch broadcasts:', error);
      toast.error('Failed to load scheduled broadcasts');
    } finally {
      setFetchingBroadcasts(false);
    }
  };

  const handleSchedule = async (scheduleData) => {
    setLoading(true);
    try {
      const response = await axios.post(`${API}/schedule/broadcast`, scheduleData, {
        headers: { Authorization: `Bearer ${user.access_token}` }
      });
      
      const { success_count, error_count, errors } = response.data;
      
      if (success_count > 0) {
        toast.success(`Successfully scheduled ${success_count} broadcast${success_count > 1 ? 's' : ''}`);
        fetchBroadcasts(); // Refresh broadcasts list
        setSelectedVideo(null); // Clear selection
      }
      
      if (error_count > 0) {
        // Show detailed error information
        const errorMessage = errors.join('\n');
        toast.error(`${error_count} broadcast${error_count > 1 ? 's' : ''} failed to schedule`, {
          description: errorMessage
        });
      }
      
      if (success_count === 0 && error_count === 0) {
        toast.error('No broadcasts were scheduled. Please check your settings.');
      }
      
    } catch (error) {
      console.error('Failed to schedule broadcasts:', error);
      const errorMessage = error.response?.data?.detail || 'Failed to schedule broadcasts';
      toast.error('Scheduling failed', {
        description: errorMessage
      });
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteBroadcast = async (broadcastId) => {
    try {
      await axios.delete(`${API}/broadcasts/${broadcastId}`, {
        headers: { Authorization: `Bearer ${user.access_token}` }
      });
      
      toast.success('Broadcast deleted successfully');
      fetchBroadcasts(); // Refresh broadcasts list
    } catch (error) {
      console.error('Failed to delete broadcast:', error);
      toast.error('Failed to delete broadcast');
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-red-100 rounded-full flex items-center justify-center">
              <Youtube className="w-6 h-6 text-red-600" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">YouTube Live Scheduler</h1>
              <p className="text-sm text-gray-600">Welcome, {user.user.name}</p>
            </div>
          </div>
          <Button variant="outline" onClick={onLogout} data-testid="logout-button">
            Logout
          </Button>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 py-8">
        <Tabs defaultValue="schedule" className="space-y-6">
          <TabsList className="grid w-full grid-cols-4 lg:w-auto">
            <TabsTrigger value="schedule" data-testid="schedule-tab">Schedule Broadcasts</TabsTrigger>
            <TabsTrigger value="upload" data-testid="upload-tab">Upload Videos</TabsTrigger>
            <TabsTrigger value="manage" data-testid="manage-tab">Manage Broadcasts</TabsTrigger>
            <TabsTrigger value="debug" data-testid="debug-tab">Debug Stream</TabsTrigger>
          </TabsList>

          <TabsContent value="schedule" className="space-y-6">
            <div className="grid lg:grid-cols-2 gap-6">
              {/* Video Selection */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <VideoIcon className="w-5 h-5" />
                    Your Videos
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {fetchingVideos ? (
                    <div className="text-center py-8">
                      <div className="w-8 h-8 border-2 border-red-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
                      <p className="text-gray-600">Loading your videos...</p>
                    </div>
                  ) : (
                    <VideoSelector
                      videos={videos}
                      onVideoSelect={setSelectedVideo}
                      selectedVideo={selectedVideo}
                    />
                  )}
                </CardContent>
              </Card>

              {/* Scheduling Form */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <CalendarIcon className="w-5 h-5" />
                    Schedule Live Streams
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ScheduleForm
                    selectedVideo={selectedVideo}
                    onSchedule={handleSchedule}
                    loading={loading}
                  />
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="upload">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <VideoIcon className="w-5 h-5" />
                  Upload Videos
                </CardTitle>
              </CardHeader>
              <CardContent>
                <VideoUploadPanel user={user} />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="manage">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Clock className="w-5 h-5" />
                  Scheduled Broadcasts
                </CardTitle>
              </CardHeader>
              <CardContent>
                {fetchingBroadcasts ? (
                  <div className="text-center py-8">
                    <div className="w-8 h-8 border-2 border-red-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
                    <p className="text-gray-600">Loading broadcasts...</p>
                  </div>
                ) : (
                  <BroadcastsList
                    broadcasts={broadcasts}
                    onDelete={handleDeleteBroadcast}
                    loading={loading}
                  />
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="debug">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <AlertCircle className="w-5 h-5" />
                  Debug Streaming
                </CardTitle>
              </CardHeader>
              <CardContent>
                <StreamingDebugPanel user={user} />
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
};

// Video upload panel
const VideoUploadPanel = ({ user }) => {
  const [uploading, setUploading] = useState(false);
  const [uploadedVideos, setUploadedVideos] = useState([]);
  const [fetchingVideos, setFetchingVideos] = useState(true);

  useEffect(() => {
    fetchUploadedVideos();
  }, []);

  const fetchUploadedVideos = async () => {
    try {
      const response = await axios.get(`${API}/uploaded-videos`, {
        headers: { Authorization: `Bearer ${user.access_token}` }
      });
      setUploadedVideos(response.data.videos || []);
    } catch (error) {
      console.error('Failed to fetch uploaded videos:', error);
      toast.error('Failed to load uploaded videos');
    } finally {
      setFetchingVideos(false);
    }
  };

  const handleFileUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    if (file.size > 500 * 1024 * 1024) { // 500MB limit
      toast.error('File too large. Maximum size is 500MB.');
      return;
    }

    setUploading(true);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await axios.post(`${API}/upload-video`, formData, {
        headers: {
          Authorization: `Bearer ${user.access_token}`,
          'Content-Type': 'multipart/form-data'
        },
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          console.log(`Upload progress: ${percentCompleted}%`);
        }
      });

      toast.success(`Video uploaded successfully! ${response.data.size_mb}MB`);
      fetchUploadedVideos(); // Refresh list
      event.target.value = ''; // Clear input
    } catch (error) {
      console.error('Upload failed:', error);
      toast.error(error.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Upload Section */}
      <div className="border-2 border-dashed border-gray-300 rounded-lg p-6">
        <div className="text-center">
          <VideoIcon className="mx-auto h-12 w-12 text-gray-400" />
          <div className="mt-4">
            <label htmlFor="video-upload" className="cursor-pointer">
              <span className="mt-2 block text-sm font-medium text-gray-900">
                Upload your video files
              </span>
              <span className="mt-1 block text-sm text-gray-600">
                MP4, AVI, MOV, MKV, WMV up to 500MB
              </span>
            </label>
            <input
              id="video-upload"
              type="file"
              className="hidden"
              accept=".mp4,.avi,.mov,.mkv,.wmv"
              onChange={handleFileUpload}
              disabled={uploading}
            />
          </div>
          <Button
            className="mt-4"
            onClick={() => document.getElementById('video-upload').click()}
            disabled={uploading}
          >
            {uploading ? (
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                Uploading...
              </div>
            ) : (
              'Choose Video File'
            )}
          </Button>
        </div>
      </div>

      {/* Uploaded Videos List */}
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Your Uploaded Videos</h3>
        {fetchingVideos ? (
          <div className="text-center py-8">
            <div className="w-6 h-6 border-2 border-red-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
            <p className="text-gray-600">Loading videos...</p>
          </div>
        ) : uploadedVideos.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            <VideoIcon className="w-12 h-12 mx-auto mb-4 text-gray-300" />
            <p>No videos uploaded yet</p>
          </div>
        ) : (
          <div className="space-y-3">
            {uploadedVideos.map((video) => (
              <Card key={video.id} className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h4 className="font-medium text-gray-900">{video.original_filename}</h4>
                    <p className="text-sm text-gray-600">
                      {Math.round(video.file_size / 1024 / 1024)}MB • 
                      Uploaded {new Date(video.upload_time).toLocaleDateString()}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      toast.success('Copy this File ID to use in scheduling: ' + video.id);
                      navigator.clipboard.writeText(video.id);
                    }}
                  >
                    Use in Schedule
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

// Streaming debug panel
const StreamingDebugPanel = ({ user }) => {
  const [videoId, setVideoId] = useState('');
  const [streamKey, setStreamKey] = useState('');
  const [testResult, setTestResult] = useState(null);
  const [testing, setTesting] = useState(false);

  const testStreaming = async () => {
    if (!videoId || !streamKey) {
      toast.error('Please enter both Video ID and Stream Key');
      return;
    }

    setTesting(true);
    setTestResult(null);

    try {
      const response = await axios.post(`${API}/test/stream`, null, {
        params: { video_id: videoId, stream_key: streamKey },
        headers: { Authorization: `Bearer ${user.access_token}` }
      });

      setTestResult(response.data);
      
      if (response.data.success) {
        toast.success('Streaming test completed successfully!');
      } else {
        toast.error('Streaming test failed. Check debug info below.');
      }
    } catch (error) {
      console.error('Test streaming failed:', error);
      setTestResult({ 
        success: false, 
        error: error.response?.data?.detail || 'Test failed',
        message: 'Request failed'
      });
      toast.error('Test request failed');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
        <h4 className="text-yellow-800 font-medium">Debug Streaming Pipeline</h4>
        <p className="text-sm text-yellow-700 mt-1">
          Test if video streaming to YouTube Live works correctly
        </p>
      </div>

      <div className="space-y-4">
        <div>
          <Label htmlFor="video-id">YouTube Video ID</Label>
          <Input
            id="video-id"
            placeholder="Enter YouTube video ID (e.g., dQw4w9WgXcQ)"
            value={videoId}
            onChange={(e) => setVideoId(e.target.value)}
          />
          <p className="text-xs text-gray-600 mt-1">
            Get this from any YouTube URL: youtube.com/watch?v=<strong>VIDEO_ID</strong>
          </p>
          <div className="mt-2 flex flex-wrap gap-1">
            <span className="text-xs text-gray-500">Quick test IDs:</span>
            {['dQw4w9WgXcQ', 'jNQXAC9IVRw', '9bZkp7q19f0'].map(id => (
              <button
                key={id}
                onClick={() => setVideoId(id)}
                className="text-xs bg-gray-100 hover:bg-gray-200 px-2 py-1 rounded"
              >
                {id}
              </button>
            ))}
          </div>
        </div>

        <div>
          <Label htmlFor="stream-key">Stream Key</Label>
          <Input
            id="stream-key"
            type="password"
            placeholder="Enter YouTube Live stream key"
            value={streamKey}
            onChange={(e) => setStreamKey(e.target.value)}
          />
          <p className="text-xs text-gray-600 mt-1">
            Get this from YouTube Studio → Go Live → Stream Settings
          </p>
        </div>

        <div className="space-y-2">
          <Button
            onClick={async () => {
              if (!videoId) {
                toast.error('Please enter a Video ID');
                return;
              }
              
              setTesting(true);
              try {
                const response = await axios.get(`${API}/test/video/${videoId}`, {
                  headers: { Authorization: `Bearer ${user.access_token}` }
                });
                
                setTestResult(response.data);
                if (response.data.success) {
                  toast.success('Video extraction successful!');
                } else {
                  toast.error('Video extraction failed');
                }
              } catch (error) {
                setTestResult({ success: false, error: 'Request failed', video_id: videoId });
                toast.error('Test request failed');
              } finally {
                setTesting(false);
              }
            }}
            disabled={testing || !videoId}
            className="w-full bg-green-600 hover:bg-green-700"
          >
            {testing ? (
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                Testing...
              </div>
            ) : (
              'Test Video Extraction Only'
            )}
          </Button>

          <Button
            onClick={testStreaming}
            disabled={testing || !videoId || !streamKey}
            className="w-full bg-blue-600 hover:bg-blue-700"
          >
            {testing ? (
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                Testing Stream...
              </div>
            ) : (
              'Test Full Streaming (30 seconds)'
            )}
          </Button>

          <Button
            onClick={async () => {
              if (!streamKey) {
                toast.error('Please enter a Stream Key');
                return;
              }
              
              setTesting(true);
              try {
                const response = await axios.post(`${API}/test/simple-stream`, null, {
                  params: { stream_key: streamKey },
                  headers: { Authorization: `Bearer ${user.access_token}` }
                });
                
                setTestResult(response.data);
                if (response.data.success) {
                  toast.success('Simple test stream started! Check YouTube Studio.');
                } else {
                  toast.error('Simple test stream failed');
                }
              } catch (error) {
                setTestResult({ success: false, error: 'Request failed', stream_key: streamKey });
                toast.error('Test request failed');
              } finally {
                setTesting(false);
              }
            }}
            disabled={testing || !streamKey}
            className="w-full bg-purple-600 hover:bg-purple-700"
          >
            {testing ? (
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                Testing...
              </div>
            ) : (
              'Test Simple Pattern Stream (60 seconds)'
            )}
          </Button>

          <Button
            onClick={async () => {
              if (!videoId || !streamKey) {
                toast.error('Please enter both Video ID and Stream Key');
                return;
              }
              
              setTesting(true);
              try {
                const response = await axios.post(`${API}/test/download-stream`, null, {
                  params: { video_id: videoId, stream_key: streamKey },
                  headers: { Authorization: `Bearer ${user.access_token}` }
                });
                
                setTestResult(response.data);
                if (response.data.success) {
                  toast.success(`Download+Stream started! File: ${response.data.file_size_mb}MB`);
                } else {
                  toast.error('Download+Stream test failed');
                }
              } catch (error) {
                setTestResult({ success: false, error: 'Request failed' });
                toast.error('Test request failed');
              } finally {
                setTesting(false);
              }
            }}
            disabled={testing || !videoId || !streamKey}
            className="w-full bg-orange-600 hover:bg-orange-700"
          >
            {testing ? (
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                Testing...
              </div>
            ) : (
              'Test Download+Stream (60 seconds)'
            )}
          </Button>
        </div>
      </div>

      {testResult && (
        <div className={`border rounded-lg p-4 ${testResult.success ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
          <h4 className={`font-medium ${testResult.success ? 'text-green-800' : 'text-red-800'}`}>
            Test Result: {testResult.success ? 'Success' : 'Failed'}
          </h4>
          
          {testResult.message && (
            <p className={`text-sm mt-1 ${testResult.success ? 'text-green-700' : 'text-red-700'}`}>
              {testResult.message}
            </p>
          )}

          {testResult.video_url && (
            <div className="mt-2">
              <p className="text-xs font-medium text-gray-700">Video URL:</p>
              <p className="text-xs text-gray-600 break-all">{testResult.video_url}</p>
            </div>
          )}

          {testResult.rtmp_url && (
            <div className="mt-2">
              <p className="text-xs font-medium text-gray-700">RTMP URL:</p>
              <p className="text-xs text-gray-600 break-all">{testResult.rtmp_url}</p>
            </div>
          )}

          {testResult.error && (
            <div className="mt-2">
              <p className="text-xs font-medium text-red-700">Error:</p>
              <p className="text-xs text-red-600">{testResult.error}</p>
            </div>
          )}

          {testResult.extraction_error && (
            <div className="mt-2">
              <p className="text-xs font-medium text-red-700">Extraction Error:</p>
              <p className="text-xs text-red-600">{testResult.extraction_error}</p>
            </div>
          )}

          {testResult.extraction_method && (
            <div className="mt-2">
              <p className="text-xs font-medium text-green-700">Extraction Method:</p>
              <p className="text-xs text-green-600">{testResult.extraction_method}</p>
            </div>
          )}

          {testResult.debug_info && (
            <div className="mt-2">
              <p className="text-xs font-medium text-gray-700">Debug Info:</p>
              <p className="text-xs text-gray-600">{testResult.debug_info}</p>
            </div>
          )}

          {testResult.file_size_mb && (
            <div className="mt-2">
              <p className="text-xs font-medium text-green-700">Downloaded File:</p>
              <p className="text-xs text-green-600">{testResult.file_size_mb}MB - {testResult.temp_file}</p>
            </div>
          )}

          {testResult.process_id && (
            <div className="mt-2">
              <p className="text-xs font-medium text-blue-700">Process Info:</p>
              <p className="text-xs text-blue-600">PID: {testResult.process_id} - Duration: {testResult.stream_duration}</p>
            </div>
          )}

          {testResult.stderr && (
            <div className="mt-2">
              <p className="text-xs font-medium text-red-700">FFmpeg Error Output:</p>
              <pre className="text-xs text-red-600 bg-red-100 p-2 rounded mt-1 overflow-auto">
                {testResult.stderr}
              </pre>
            </div>
          )}
        </div>
      )}

      <div className="bg-gray-50 border rounded-lg p-4">
        <h4 className="font-medium text-gray-800">How to use this:</h4>
        <ol className="text-sm text-gray-600 mt-2 space-y-1 list-decimal list-inside">
          <li><strong>Step 1:</strong> Use one of the quick test video IDs or enter your own <strong>existing/completed</strong> video ID</li>
          <li><strong>Step 2:</strong> Click "Test Video Extraction Only" to verify it works</li>
          <li><strong>Step 3:</strong> Go to YouTube Studio → Create → Go Live and copy the Stream Key</li>
          <li><strong>Step 4:</strong> Enter the Stream Key and click "Test Full Streaming"</li>
          <li><strong>Step 5:</strong> Check YouTube Studio to see if the stream appears</li>
        </ol>
        <div className="mt-3 p-2 bg-yellow-50 border border-yellow-200 rounded">
          <p className="text-xs text-yellow-800">
            ⚠️ <strong>Important:</strong> Don't use future live events or private videos. Use existing, public videos for testing.
          </p>
        </div>
      </div>
    </div>
  );
};

// Auth callback handler
const AuthCallback = ({ onAuth }) => {
  useEffect(() => {
    const handleCallback = async () => {
      const urlParams = new URLSearchParams(window.location.search);
      const code = urlParams.get('code');
      
      if (code) {
        try {
          const response = await axios.post(`${API}/auth/callback`, { code });
          onAuth(response.data);
        } catch (error) {
          console.error('Auth callback failed:', error);
          toast.error('Authentication failed');
          window.location.href = '/';
        }
      }
    };

    handleCallback();
  }, [onAuth]);

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-red-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
        <p>Completing authentication...</p>
      </div>
    </div>
  );
};

// Main App component
function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check for stored auth
    const storedAuth = localStorage.getItem('youtube_auth');
    if (storedAuth) {
      try {
        const authData = JSON.parse(storedAuth);
        setUser(authData);
      } catch (error) {
        localStorage.removeItem('youtube_auth');
      }
    }
    setLoading(false);
  }, []);

  const handleAuth = (authData) => {
    setUser(authData);
    localStorage.setItem('youtube_auth', JSON.stringify(authData));
    window.history.replaceState({}, '', '/');
  };

  const handleLogout = () => {
    setUser(null);
    localStorage.removeItem('youtube_auth');
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-red-600 border-t-transparent rounded-full animate-spin"></div>
      </div>
    );
  }

  return (
    <div className="App">
      <Toaster position="top-right" />
      <BrowserRouter>
        <Routes>
          <Route 
            path="/auth/callback" 
            element={<AuthCallback onAuth={handleAuth} />} 
          />
          <Route 
            path="/" 
            element={
              user ? (
                <Dashboard user={user} onLogout={handleLogout} />
              ) : (
                <AuthPage onAuth={handleAuth} />
              )
            } 
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;