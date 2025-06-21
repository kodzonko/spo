<p align="center">
  <a href="https://coveralls.io/github/kodzonko/spo?branch=master">
    <img src="https://coveralls.io/repos/github/kodzonko/spo/badge.svg?branch=master" alt="Coverage Status"/>
  </a>
  <a href="https://www.python.org/downloads/release/python-3130/">
    <img src="https://img.shields.io/badge/python-3.13-blue.svg" alt="Python 3.13"/>
  </a>
  <a href="https://docs.astral.sh/ruff/">
    <img src="https://img.shields.io/badge/code%20style-ruff-005A9C.svg?logo=ruff" alt="Ruff"/>
  </a>
</p>

# SPO - Spotify to YouTube Music Sync

A comprehensive Python tool for synchronizing playlists between Spotify and YouTube Music with built-in API rate limiting and throttling.

## 🚀 Features

- **Spotify Integration**: Secure authentication with automatic and manual fallback modes
- **YouTube Music Integration**: Full support for YouTube Music playlist operations
- **API Rate Limiting**: Advanced throttling mechanism to prevent rate limit violations
- **Graceful Error Handling**: Automatic retries with exponential backoff for failed requests
- **User-Friendly**: Simple setup with environment variable configuration
- **Robust Authentication**: Handles token refresh and authentication errors automatically
- **Type Safety**: Full type hints and mypy support

## 📦 Installation

### Prerequisites

- Python 3.13 or higher
- Spotify Developer Account
- YouTube Music Account

### Setup

```bash
# Clone the repository
git clone git@github.com:kodzonko/spo.git
cd spo

# Install dependencies
uv pip install -e .

# Install development dependencies (optional)
uv pip install -e ".[dev]"
```

## ⚙️ Configuration

### Spotify Setup

1. Create a web application on the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/applications)
2. Follow the [Getting Started with Web API](https://developer.spotify.com/documentation/web-api/tutorials/getting-started) guide
3. Your app dashboard should look like this:

<p align="center">
  <img src="docs/spotify-app-dashboard.jpg" alt="Spotify App Dashboard" width="600"/>
</p>

### Environment Variables

Create an `.env` file in the project root:

```env
# Spotify Configuration
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
SPOTIFY_REDIRECT_URI=http://localhost:8080/callback
```

## 🎯 Quick Start

### Basic Spotify Usage

```python
from spo.spotify_client import SpotifyClient

# Initialize client with automatic throttling
with SpotifyClient() as client:
    # Search for tracks (automatically throttled)
    tracks = client.search_tracks("Bohemian Rhapsody", limit=10)

    # Get user playlists (automatically throttled)
    playlists = client.get_user_playlists(limit=20)

    # Get saved tracks (automatically throttled)
    saved_tracks = client.get_user_saved_tracks(limit=50)
```

### YouTube Music Integration

```python
from spo.youtube_music_client import YouTubeMusicClient

# Initialize YouTube Music client
with YouTubeMusicClient() as client:
    # Search for tracks
    tracks = client.search_tracks("Bohemian Rhapsody", limit=10)
    
    # Get user playlists
    playlists = client.get_user_playlists()
    
    # Create or update playlists
    playlist_id = client.create_playlist("My Synced Playlist", "Description")
```

## 🔧 API Rate Limiting

This project includes a sophisticated throttling mechanism that prevents API rate limit violations and handles rate limits gracefully.

### Key Features

- **Token Bucket Algorithm**: Handles burst requests efficiently
- **Sliding Window**: Enforces per-minute rate limits
- **Exponential Backoff**: Automatic retry with increasing delays
- **Spotify Optimization**: Pre-configured limits optimized for Spotify's API
- **Transparent Integration**: No code changes required - just add decorators

### How It Works

All Spotify API methods are automatically decorated with `@spotify_throttle()`, which:

1. **Prevents Rate Limits**: Limits requests to 0.5/second and 30/minute by default
2. **Handles 429 Responses**: Automatically retries with proper delays
3. **Manages Bursts**: Allows up to 5 rapid requests before throttling
4. **Logs Activity**: Provides detailed logging for monitoring and debugging

### Example Output

```
🔍 Search 1/5: 'Bohemian Rhapsody'
   ✅ Found 3 tracks in 0.45s
🔍 Search 2/5: 'Billie Jean'
   ✅ Found 3 tracks in 2.12s  # Rate limited - waited before request
🔍 Search 3/5: 'Hotel California'
   ✅ Found 3 tracks in 2.08s
```

## 🛠️ Advanced Usage

### Custom Throttling

```python
from spo.throttling import throttle, spotify_throttle

# Custom rate limits
@throttle(requests_per_second=1.0, max_retries=3)
def custom_api_call(self):
    return self._spotify.some_endpoint()

# Spotify-optimized throttling
@spotify_throttle(requests_per_minute=20)
def conservative_api_call(self):
    return self._spotify.another_endpoint()
```

### Error Handling

```python
try:
    tracks = client.search_tracks("query")
except spotipy.SpotifyException as e:
    if e.http_status == 429:
        print("Rate limited (should be handled automatically)")
    elif e.http_status == 401:
        print("Authentication error")
    else:
        print(f"API error: {e}")
```

### Playlist Synchronization

```python
from spo.spotify_client import SpotifyClient
from spo.youtube_music_client import YouTubeMusicClient

# Sync a playlist from Spotify to YouTube Music
with SpotifyClient() as spotify, YouTubeMusicClient() as ytmusic:
    # Get Spotify playlist
    spotify_playlist = spotify.get_playlist_tracks("spotify_playlist_id")
    
    # Create YouTube Music playlist
    yt_playlist_id = ytmusic.create_playlist("Synced Playlist", "From Spotify")
    
    # Add tracks to YouTube Music playlist
    for track in spotify_playlist:
        ytmusic.add_tracks_to_playlist(yt_playlist_id, [track])
```

## 🧪 Testing

Run the test suite:

```bash
# Run all tests
python -m pytest tests/

# Run specific test files
python -m pytest tests/test_spotify_client.py -v
python -m pytest tests/test_youtube_music_client.py -v
python -m pytest tests/test_throttling.py -v

# Run with coverage
python -m pytest tests/ --cov=spo --cov-report=html
```

## 📁 Project Structure

```
spo/
├── src/spo/
│   ├── __init__.py
│   ├── main.py                 # Main application entry point
│   ├── spotify_client.py       # Spotify API client with throttling
│   ├── youtube_music_client.py # YouTube Music API client
│   ├── throttling.py           # Rate limiting and retry logic
│   ├── auth_server.py          # Authentication server
│   └── py.typed               # Type hints marker
├── tests/
│   ├── conftest.py            # Test configuration
│   ├── test_spotify_client.py # Spotify client tests
│   ├── test_youtube_music_client.py # YouTube Music client tests
│   ├── test_throttling.py     # Throttling mechanism tests
│   └── test_auth_server.py    # Authentication tests
├── docs/
│   └── spotify-app-dashboard.jpg # Spotify setup screenshot
├── pyproject.toml             # Project configuration
├── uv.lock                    # Dependency lock file
└── README.md
```

## 🤝 Contributing

We welcome contributions! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Add tests for new functionality
4. Ensure all tests pass (`python -m pytest tests/`)
5. Run linting (`ruff check src/ tests/`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

### Development Setup

```bash
# Install development dependencies
uv pip install -e ".[dev]"

# Run pre-commit hooks
pre-commit install

# Run type checking
mypy src/

# Run linting
ruff check src/ tests/
ruff format src/ tests/
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Spotipy](https://github.com/spotipy-dev/spotipy) - Spotify Web API wrapper
- [ytmusicapi](https://github.com/sigma67/ytmusicapi) - YouTube Music API wrapper
- [Loguru](https://github.com/Delgan/loguru) - Advanced logging library
