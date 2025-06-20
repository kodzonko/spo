# Spotify API Throttling Mechanism

This document describes the comprehensive throttling mechanism implemented to prevent API rate limit violations and handle rate limits gracefully when interacting with the Spotify Web API.

## Overview

The throttling mechanism provides:

- **Rate Limiting**: Prevents exceeding API rate limits using token bucket and sliding window algorithms
- **Automatic Retries**: Handles 429 (Too Many Requests) responses with exponential backoff
- **Graceful Error Handling**: Manages connection errors and server errors appropriately
- **Configurable Limits**: Customizable rate limits and retry policies
- **Per-Client Support**: Optional per-client rate limiting for multi-client scenarios

## Architecture

### Core Components

1. **ThrottleManager**: Core class managing rate limiting logic
2. **@throttle**: General-purpose throttling decorator
3. **@spotify_throttle**: Spotify-optimized throttling decorator
4. **Token Bucket Algorithm**: Handles burst requests
5. **Sliding Window Algorithm**: Enforces per-minute rate limits

### Rate Limiting Algorithms

#### Token Bucket

- Allows burst requests up to `burst_size`
- Refills tokens at `requests_per_second` rate
- Prevents sustained high request rates

#### Sliding Window

- Tracks requests in the last 60 seconds
- Enforces `requests_per_minute` limit
- Automatically removes old requests from tracking

## Usage

### Basic Usage

```python
from spo.throttling import spotify_throttle

class SpotifyClient:
    @spotify_throttle()
    def search_tracks(self, query: str, limit: int = 10):
        return self._spotify.search(q=query, type="track", limit=limit)
```

### Custom Configuration

```python
from spo.throttling import throttle

@throttle(
    requests_per_second=1.0,
    requests_per_minute=50,
    burst_size=8,
    max_retries=3,
    base_delay=2.0,
    max_delay=30.0
)
def custom_api_call(self):
    return self._spotify.some_api_call()
```

### Advanced Usage with Client ID

```python
def extract_client_id(*args, **kwargs):
    # Extract client identifier from function arguments
    return args[0].client_id if args else None

@throttle(client_id_func=extract_client_id)
def multi_client_api_call(self, data):
    return self._spotify.api_call(data)
```

## Configuration Options

### Spotify-Optimized Defaults

The `@spotify_throttle` decorator uses conservative defaults optimized for Spotify's API:

```python
requests_per_second = 0.5   # Conservative rate for Spotify
requests_per_minute = 30    # Conservative minute limit
burst_size = 5              # Small burst allowance
max_retries = 5             # Retry failed requests
```

### General Throttle Parameters

| Parameter             | Type            | Default | Description                                  |
| --------------------- | --------------- | ------- | -------------------------------------------- |
| `requests_per_second` | float           | 1.0     | Maximum requests per second                  |
| `requests_per_minute` | int             | 60      | Maximum requests per minute                  |
| `burst_size`          | int             | 10      | Maximum burst requests allowed               |
| `max_retries`         | int             | 5       | Maximum retry attempts for failed requests   |
| `base_delay`          | float           | 1.0     | Base delay for exponential backoff (seconds) |
| `max_delay`           | float           | 60.0    | Maximum delay between retries (seconds)      |
| `backoff_multiplier`  | float           | 2.0     | Multiplier for exponential backoff           |
| `client_id_func`      | Callable        | None    | Function to extract client ID from args      |
| `manager`             | ThrottleManager | None    | Custom throttle manager instance             |

## Error Handling

### Automatic Retry Scenarios

The throttling mechanism automatically retries requests in these situations:

1. **429 Too Many Requests**: Uses `Retry-After` header if available
2. **5xx Server Errors**: Temporary server issues (500, 502, 503, 504)
3. **Connection Errors**: Network timeouts and connection issues

### Non-Retry Scenarios

These errors are not retried and are raised immediately:

1. **4xx Client Errors** (except 429): Authentication, invalid requests, etc.
2. **Application Logic Errors**: Invalid parameters, missing data, etc.

### Exponential Backoff

Retry delays follow exponential backoff with jitter:

```
delay = min(base_delay * (backoff_multiplier ^ attempt), max_delay) + jitter
```

Jitter (10-30% of delay) prevents thundering herd problems.

## Logging

The throttling mechanism provides detailed logging:

```python
import logging
logging.getLogger('spo.throttling').setLevel(logging.DEBUG)
```

### Log Levels

- **DEBUG**: Individual request attempts and rate limit waits
- **INFO**: Successful retries after failures
- **WARNING**: Rate limits hit, server errors with retry
- **ERROR**: Permanent failures after all retries

## Performance Considerations

### Memory Usage

- Token buckets: O(1) per client
- Request tracking: O(requests_per_minute) per client
- Old requests automatically cleaned up

### CPU Overhead

- Minimal overhead per request
- Token refill calculations: O(1)
- Request window cleanup: O(requests_per_minute)

### Network Efficiency

- Prevents unnecessary requests through rate limiting
- Reduces server load and improves overall performance
- Handles burst scenarios efficiently

## Best Practices

### 1. Use Appropriate Rate Limits

```python
# For high-frequency operations
@spotify_throttle(requests_per_second=0.3, requests_per_minute=15)
def batch_operation(self):
    pass

# For user-interactive operations
@spotify_throttle(requests_per_second=1.0, requests_per_minute=30)
def user_search(self):
    pass
```

### 2. Handle Exceptions Gracefully

```python
@spotify_throttle()
def safe_api_call(self):
    try:
        return self._spotify.api_call()
    except spotipy.SpotifyException as e:
        if e.http_status == 401:
            # Handle authentication errors
            self.refresh_token()
            raise
        # Other errors will be handled by throttling decorator
        raise
```

### 3. Monitor Rate Limit Usage

```python
import logging

# Enable throttling logs
logging.getLogger('spo.throttling').setLevel(logging.INFO)

# Monitor your application's rate limit behavior
```

### 4. Configure for Your Use Case

```python
# For batch processing
@throttle(
    requests_per_second=0.2,   # Very conservative
    requests_per_minute=10,    # Low total volume
    burst_size=2,              # Minimal bursts
    max_retries=10             # More retries for batch jobs
)
def batch_processor(self):
    pass

# For interactive applications
@throttle(
    requests_per_second=1.0,   # Responsive
    requests_per_minute=40,    # Reasonable volume
    burst_size=8,              # Handle user bursts
    max_retries=3              # Quick failure for UX
)
def interactive_feature(self):
    pass
```

## Troubleshooting

### Common Issues

1. **Still hitting rate limits**: Reduce `requests_per_second` and `requests_per_minute`
2. **Too slow**: Increase rate limits gradually while monitoring
3. **High memory usage**: Check for client ID leaks in per-client mode
4. **Logs show constant retries**: Check network connectivity and API status

### Monitoring Rate Limit Health

```python
from spo.throttling import _default_throttle_manager

# Check current token count
print(f"Available tokens: {_default_throttle_manager.tokens}")

# Check recent request count
print(f"Recent requests: {len(_default_throttle_manager.request_times)}")
```

## Examples

### Simple Search with Throttling

```python
from spo.spotify_client import SpotifyClient

with SpotifyClient() as client:
    # Automatically throttled
    tracks = client.search_tracks("Bohemian Rhapsody")
    print(f"Found {len(tracks)} tracks")
```

### Batch Processing with Custom Rates

```python
from spo.throttling import throttle

class BatchProcessor:
    @throttle(requests_per_second=0.1, max_retries=10)
    def process_playlist(self, playlist_id):
        return self.spotify.playlist(playlist_id)

    def process_all_playlists(self, playlist_ids):
        results = []
        for playlist_id in playlist_ids:
            try:
                playlist = self.process_playlist(playlist_id)
                results.append(playlist)
            except Exception as e:
                print(f"Failed to process {playlist_id}: {e}")
        return results
```

### Error Handling Example

```python
@spotify_throttle()
def robust_track_search(self, query):
    try:
        return self._spotify.search(query, type="track")
    except spotipy.SpotifyException as e:
        if e.http_status == 429:
            # This should be handled by decorator, but just in case
            print("Rate limited - decorator should have handled this")
            raise
        elif e.http_status == 401:
            # Authentication error - refresh token
            self.refresh_authentication()
            raise
        else:
            # Other client errors
            print(f"API error: {e}")
            raise
    except Exception as e:
        # Network or other errors
        print(f"Unexpected error: {e}")
        raise
```

## Integration with Existing Code

The throttling mechanism is designed to be non-intrusive. Simply add the decorator to existing methods:

```python
# Before
def search_tracks(self, query):
    return self._spotify.search(q=query, type="track")

# After
@spotify_throttle()
def search_tracks(self, query):
    return self._spotify.search(q=query, type="track")
```

No other changes to your code are required. The decorator handles all throttling logic transparently.
