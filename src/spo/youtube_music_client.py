import json
import os

from loguru import logger
from ytmusicapi import YTMusic


class YouTubeMusicClient:
    """
    YouTube Music API client with authentication and credential caching.
    Supports authentication via browser headers or OAuth credentials.
    """

    def __init__(self) -> None:
        """
        Initialize the YouTube Music client with authentication handling.

        Raises:
            Exception: If authentication fails
        """
        self._ytmusic: YTMusic | None = None
        self._user: dict | None = None
        self._headers_path = os.getenv("YTMUSIC_HEADERS_PATH", ".ytmusic_headers.json")
        self._oauth_path = os.getenv("YTMUSIC_OAUTH_PATH", ".ytmusic_oauth.json")
        self._authenticate()

    def _authenticate(self) -> None:
        """
        Authenticate with YouTube Music using browser headers or OAuth.
        """
        # Try OAuth credentials first if available
        if os.path.exists(self._oauth_path):
            try:
                logger.info(
                    f"🔑 Authenticating with OAuth credentials: {self._oauth_path}"
                )
                self._ytmusic = YTMusic(self._oauth_path)
                self._user = self._get_user_profile()
                logger.success("✅ Successfully authenticated with OAuth credentials!")
                return
            except Exception as e:
                logger.warning(f"❌ OAuth authentication failed: {e}")

        # Fallback to browser headers
        headers_file = None
        if os.path.exists(self._headers_path):
            headers_file = self._headers_path
        elif os.path.exists("browser.json"):
            # Auto-copy browser.json to .ytmusic_headers.json if missing

            try:
                # Normalize header keys to lowercase for ytmusicapi compatibility
                with open("browser.json", "r", encoding="utf-8") as f:
                    headers = json.load(f)
                headers = {k.lower(): v for k, v in headers.items()}
                with open(self._headers_path, "w", encoding="utf-8") as f:
                    json.dump(headers, f, indent=2)
                logger.info(
                    f"Copied and normalized browser.json to {self._headers_path} for YTMusic compatibility."
                )
                headers_file = self._headers_path
            except Exception as e:
                logger.warning(
                    f"Failed to copy browser.json to {self._headers_path}: {e}"
                )

        if headers_file:
            try:
                logger.info(f"🔑 Authenticating with browser headers: {headers_file}")
                # Load headers directly instead of passing file path to avoid OAuth interpretation
                with open(headers_file, "r", encoding="utf-8") as f:
                    headers = json.load(f)
                self._ytmusic = YTMusic(headers)
                self._user = self._get_user_profile()
                logger.success("✅ Successfully authenticated with browser headers!")
                return
            except Exception as e:
                logger.warning(f"❌ Browser header authentication failed: {e}")

        # Check if we have OAuth client secrets before attempting OAuth setup
        oauth_client_secret = os.getenv("YTMUSIC_CLIENT_SECRET")

        if oauth_client_secret:
            # Attempt browser-based OAuth setup if we have client secrets
            try:
                logger.info(
                    "No valid YouTube Music authentication found. Initiating browser-based OAuth flow..."
                )
                from ytmusicapi import setup_oauth

                setup_oauth(self._oauth_path, oauth_client_secret)
                logger.success(
                    "✅ OAuth authentication completed. Please rerun your command."
                )
                self._ytmusic = YTMusic(self._oauth_path)
                self._user = self._get_user_profile()
                return
            except Exception as e:
                logger.error(f"❌ Browser-based OAuth authentication failed: {e}")
        else:
            logger.warning(
                "⚠️  OAuth client secret not found. Skipping OAuth setup. "
                "Set YTMUSIC_CLIENT_SECRET environment variable to enable OAuth authentication."
            )

        # If we get here, no authentication method worked
        logger.error(
            "No valid YouTube Music authentication found.\n"
            "Please do one of the following:\n"
            f"1. Export your request headers from YouTube Music and save them as {self._headers_path}\n"
            f"2. Provide OAuth credentials as {self._oauth_path}\n"
            "3. Set YTMUSIC_CLIENT_SECRET environment variable and ensure browser.json contains valid headers"
        )
        raise Exception("YouTube Music authentication required.")

    @property
    def is_authenticated(self) -> bool:
        """Check if the client is successfully authenticated."""
        return self._ytmusic is not None and self._user is not None

    @property
    def current_user(self) -> dict:
        """Get current user information."""
        if not self.is_authenticated or self._user is None:
            raise Exception("Client is not authenticated")
        return self._user

    @property
    def user_info(self) -> str:
        """Get formatted user information string."""
        user = self.current_user
        return f"{user.get('name', 'Unknown')} ({user.get('email', 'N/A')})"

    def _get_user_profile(self) -> dict:
        """
        Attempt to retrieve user profile information.
        Note: ytmusicapi does not provide direct user profile access,
        so this is a placeholder for future expansion.
        """
        # ytmusicapi does not expose user info, so return minimal info
        return {"name": "YouTube Music User", "email": "N/A"}

    def search_tracks(self, query: str, limit: int = 10) -> list:
        """
        Search for tracks using the YouTube Music API.

        Args:
            query: Search query string
            limit: Number of results to return (default: 10)

        Returns:
            list: List of track information dictionaries
        """
        if not self.is_authenticated or self._ytmusic is None:
            raise Exception("Client is not authenticated")

        try:
            results = self._ytmusic.search(query, filter="songs", limit=limit)
            tracks = []
            for track in results:
                album = track.get("album")
                album_name = album.get("name", "Unknown") if album else "Unknown"
                tracks.append(
                    {
                        "videoId": track.get("videoId"),
                        "title": track.get("title"),
                        "artist": track.get("artists", [{}])[0].get("name", "Unknown"),
                        "album": album_name,
                        "duration": track.get("duration"),
                    }
                )
            return tracks
        except Exception as e:
            logger.error(f"❌ Failed to search tracks: {e}")
            return []

    def get_user_playlists(self, limit: int = 10) -> list:
        """
        Get the current user's playlists.

        Args:
            limit: Number of playlists to return (default: 10)

        Returns:
            list: List of playlist information dictionaries
        """
        if not self.is_authenticated or self._ytmusic is None:
            raise Exception("Client is not authenticated")

        try:
            playlists = self._ytmusic.get_library_playlists(limit=limit)
            return [
                {
                    "playlistId": pl.get("playlistId"),
                    "title": pl.get("title"),
                    "trackCount": pl.get("count"),
                }
                for pl in playlists
            ]
        except Exception as e:
            logger.error(f"❌ Failed to get playlists: {e}")
            return []

    def get_user_saved_tracks(self, limit: int = 10) -> list:
        """
        Get the current user's liked songs.

        Args:
            limit: Number of saved tracks to return (default: 10)

        Returns:
            list: List of saved track information dictionaries
        """
        if not self.is_authenticated or self._ytmusic is None:
            raise Exception("Client is not authenticated")

        try:
            liked_songs = self._ytmusic.get_liked_songs(limit=limit)

            if not isinstance(liked_songs, dict):
                logger.warning(
                    f"❌ get_liked_songs returned type: {type(liked_songs)} value: {liked_songs}"
                )
                return []
            if "tracks" not in liked_songs:
                logger.warning(
                    f"❌ get_liked_songs returned dict without 'tracks' key: {liked_songs}"
                )
                return []
            if not isinstance(liked_songs["tracks"], list):
                logger.warning(
                    f"❌ liked_songs['tracks'] is not a list: {liked_songs['tracks']}"
                )
                return []
            tracks = []
            for item in liked_songs["tracks"]:
                if not isinstance(item, dict):
                    logger.warning(f"❌ Skipping non-dict item in tracks: {item}")
                    continue
                album = item.get("album")
                album_name = album.get("name", "Unknown") if album else "Unknown"
                tracks.append(
                    {
                        "videoId": item.get("videoId"),
                        "title": item.get("title"),
                        "artist": item.get("artists", [{}])[0].get("name", "Unknown"),
                        "album": album_name,
                        "duration": item.get("duration"),
                    }
                )
            return tracks
        except Exception as e:
            logger.error(f"❌ Failed to get liked songs: {e}")
            return []
