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
    const now = new Date();
    const times = showCustomTimes ? customTimes : ['05:55', '06:55', '07:55', '16:55', '17:55'];
    
    // Check if selected date is in the past
    if (selectedDate < new Date(now.getFullYear(), now.getMonth(), now.getDate())) {
      errors.push('Selected date cannot be in the past');
      return errors;
    }

    times.forEach((timeStr, index) => {
      const [hour, minute] = timeStr.split(':').map(Number);
      const scheduleDateTime = new Date(selectedDate);
      scheduleDateTime.setHours(hour, minute, 0, 0);

      const timeDiff = scheduleDateTime - now;
      const minutesFromNow = timeDiff / (1000 * 60);

      if (minutesFromNow < 15) {
        errors.push(`Time ${timeStr}: Must be at least 15 minutes in the future`);
      }

      if (timeDiff > 180 * 24 * 60 * 60 * 1000) { // 180 days in milliseconds
        errors.push(`Time ${timeStr}: Cannot schedule more than 6 months in advance`);
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
        <p className="text-sm text-gray-600">
          ⏰ Broadcasts can be scheduled 15 minutes to 6 months from now (IST timezone)
        </p>
        <p className="text-xs text-blue-600">
          🌍 Current IST time: {new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}
        </p>
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
            <p className="text-sm text-gray-600 mb-2">Default broadcast times:</p>
            <div className="flex flex-wrap gap-2">
              {['05:55', '06:55', '07:55', '16:55', '17:55'].map((time, index) => (
                <Badge key={index} className="bg-red-100 text-red-800">{time}</Badge>
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
      case 'live': return 'destructive';
      case 'completed': return 'secondary';
      case 'error': return 'destructive';
      default: return 'default';
    }
  };

  const formatDateTime = (dateTime) => {
    return new Date(dateTime).toLocaleString('en-US', {
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
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
        {broadcasts.map((broadcast) => (
          <Card key={broadcast.id} data-testid={`broadcast-card-${broadcast.id}`}>
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
          <TabsList className="grid w-full grid-cols-2 lg:w-auto">
            <TabsTrigger value="schedule" data-testid="schedule-tab">Schedule Broadcasts</TabsTrigger>
            <TabsTrigger value="manage" data-testid="manage-tab">Manage Broadcasts</TabsTrigger>
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
        </Tabs>
      </main>
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