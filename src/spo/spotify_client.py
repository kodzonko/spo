import os
import socket
import webbrowser

import spotipy
from dotenv import load_dotenv
from loguru import logger
from spotipy.oauth2 import SpotifyOAuth

from spo.auth_server import AuthServer
from spo.throttling import spotify_throttle


class SpotifyClient:
    """
    Spotify API client with automatic redirect capture and graceful fallback.

    This client tries automatic redirect capture first (best user experience),
    then falls back to manual copy-paste if redirect URIs aren't configured.
    """

    def __init__(self) -> None:
        """
        Initialize the Spotify client with robust authentication handling.

        Raises:
            ValueError: If required environment variables are missing
            Exception: If all authentication methods fail
        """
        self._spotify: spotipy.Spotify | None = None
        self._scopes = "user-library-read playlist-read-private user-read-private"
        self._cache_path = ".spo_auth"
        self._user: dict | None = None
        self._authenticate()

    def _authenticate(self) -> None:
        """
        Authenticate with Spotify using the most appropriate method.

        Tries automatic capture first, falls back to manual if needed.
        """
        # Load environment variables
        load_dotenv()

        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")

        if not client_id or not client_secret:
            raise ValueError(
                "Missing Spotify credentials. Please ensure SPOTIFY_CLIENT_ID and "
                "SPOTIFY_CLIENT_SECRET are set in your .env file."
            )

        # Check if automatic capture is possible by looking for localhost redirect URIs
        redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "")

        if "localhost" in redirect_uri.lower():
            # Try automatic capture with common registered ports
            registered_ports = [8080, 8081, 8082, 3000, 8000]

            for port in registered_ports:
                if self._is_port_available(port):
                    try:
                        logger.info(
                            f"🚀 Attempting automatic capture on port {port}..."
                        )
                        self._authenticate_automatic(client_id, client_secret, port)
                        return
                    except Exception as e:
                        error_msg = str(e).lower()
                        if "invalid" in error_msg and (
                            "redirect" in error_msg or "client" in error_msg
                        ):
                            logger.warning(
                                f"❌ Port {port} not registered as redirect URI"
                            )
                            continue
                        else:
                            # Some other error, try fallback to manual
                            logger.warning(f"Automatic authentication failed: {e}")
                            break

            # All automatic attempts failed, fall back to manual
            logger.warning(
                "\n📋 Automatic redirect capture failed - falling back to manual method"
            )
            logger.info("\n💡 To enable automatic capture in the future:")
            logger.info("   1. Go to: https://developer.spotify.com/dashboard")
            logger.info("   2. Click your app → Edit Settings → Redirect URIs")
            logger.info("   3. Add: http://localhost:8080/callback")
            logger.info("   4. Save and try again")
            logger.info("")
        else:
            logger.info(
                "🔧 Using manual authentication (no localhost redirect URI configured)"
            )
            logger.info(f"📋 Using redirect URI: {redirect_uri}")
            logger.info("")

        self._authenticate_manual(client_id, client_secret)

    def _authenticate_automatic(
        self, client_id: str, client_secret: str, port: int
    ) -> None:
        """Authenticate using automatic redirect capture."""
        # Start local server
        auth_server = AuthServer(port=port)
        callback_url = auth_server.start()

        try:
            logger.info(f"🔗 Using redirect URI: {callback_url}")
            # Create OAuth manager with dynamic redirect URI
            auth_manager = SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=callback_url,
                scope=self._scopes,
                cache_path=self._cache_path,
                show_dialog=True,
            )

            # Check for cached token first
            token_info = auth_manager.get_cached_token()

            if not token_info:
                # Get authorization URL and open in browser
                auth_url = auth_manager.get_authorize_url()
                logger.info("🌐 Opening browser for authorization...")
                logger.info(f"📋 Authorization URL: {auth_url}")
                logger.info("")
                logger.info("📝 IMPORTANT: After clicking 'Agree' in Spotify:")
                logger.info("   1. You should see a success page with green checkmark")
                logger.info("   2. The browser tab should close automatically")
                logger.info(
                    "   3. If you see an error, check your redirect URI configuration"
                )
                logger.info("")

                import webbrowser

                webbrowser.open(auth_url)

                logger.info("⏳ Waiting for authorization callback...")
                logger.info(
                    "💡 If this hangs, try refreshing the browser or check for popup blockers"
                )

                # Wait for callback
                auth_code, auth_error = auth_server.wait_for_callback(timeout=120)

                if auth_error:
                    raise Exception(f"Authorization failed: {auth_error}")

                if not auth_code:
                    raise Exception("No authorization code received")

                logger.success("✅ Authorization code received!")

                # Exchange code for token
                token_info = auth_manager.get_access_token(auth_code)

            # Create authenticated client
            self._spotify = spotipy.Spotify(auth_manager=auth_manager)
            self._user = self._spotify.current_user()

            if self._user is None:
                raise Exception("Failed to get user information")

            logger.success(
                "✅ Successfully authenticated using automatic redirect capture!"
            )
            logger.info(
                f"👤 Logged in as: {self._user['display_name']} (@{self._user['id']})"
            )

        finally:
            auth_server.stop()

    def _authenticate_manual(self, client_id: str, client_secret: str) -> None:
        """Authenticate using manual copy-paste method."""
        redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "https://spotify.com/")
        logger.info(f"🔗 Using redirect URI: {redirect_uri}")

        # Create OAuth manager with static redirect URI
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=self._scopes,
            cache_path=self._cache_path,
            show_dialog=True,
        )

        # Check for cached token first
        token_info = auth_manager.get_cached_token()

        if not token_info:
            # Get authorization URL
            auth_url = auth_manager.get_authorize_url()
            logger.info("🌐 Please visit this URL to authorize the application:")
            logger.info(f"📋 {auth_url}")
            logger.info("")

            # Open in browser
            webbrowser.open(auth_url)

            # Get redirect URL from user
            logger.info("After authorizing, you'll be redirected to a URL.")
            logger.info("Please copy and paste the full redirect URL here:")
            redirect_response = input("📝 Redirect URL: ").strip()

            # Extract authorization code
            from urllib.parse import parse_qs, urlparse

            parsed_url = urlparse(redirect_response)

            if parsed_url.query:
                params = parse_qs(parsed_url.query)
                if "code" in params:
                    auth_code = params["code"][0]
                    logger.success("✅ Authorization code extracted!")

                    # Exchange code for token
                    token_info = auth_manager.get_access_token(auth_code)
                else:
                    raise Exception("No authorization code found in redirect URL")
            else:
                raise Exception("Invalid redirect URL format")

        # Create authenticated client
        self._spotify = spotipy.Spotify(auth_manager=auth_manager)
        self._user = self._spotify.current_user()

        if self._user is None:
            raise Exception("Failed to get user information")

        logger.success("✅ Successfully authenticated using manual method!")
        logger.info(
            f"👤 Logged in as: {self._user['display_name']} (@{self._user['id']})"
        )

    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available for use."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("localhost", port))
                return True
        except Exception:
            return False

    @property
    def is_authenticated(self) -> bool:
        """Check if the client is successfully authenticated."""
        return self._spotify is not None and self._user is not None

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
        return f"{user['display_name']} (@{user['id']})"

    @spotify_throttle()
    def get_track_info(self, track_id: str) -> dict:
        """
        Get detailed information about a specific track.

        Args:
            track_id: Spotify track ID

        Returns:
            dict: Track information including name, artist, album, popularity, and preview URL
        """
        if not self.is_authenticated or self._spotify is None:
            raise Exception("Client is not authenticated")

        try:
            track = self._spotify.track(track_id)
            if track is None:
                logger.error("❌ Track not found")
                return {}

            return {
                "name": track["name"],
                "artist": track["artists"][0]["name"],
                "album": track["album"]["name"],
                "popularity": track["popularity"],
                "preview_url": track["preview_url"],
            }
        except Exception as e:
            logger.error(f"❌ Failed to get track info: {e}")
            return {}

    @spotify_throttle()
    def search_tracks(self, query: str, limit: int = 10) -> list:
        """
        Search for tracks using the Spotify API.

        Args:
            query: Search query string
            limit: Number of results to return (default: 10)

        Returns:
            list: List of track information dictionaries
        """
        if not self.is_authenticated or self._spotify is None:
            raise Exception("Client is not authenticated")

        try:
            results = self._spotify.search(q=query, type="track", limit=limit)
            if results is None or "tracks" not in results:
                logger.error("❌ No search results found")
                return []

            tracks = []

            for track in results["tracks"]["items"]:
                tracks.append(
                    {
                        "id": track["id"],
                        "name": track["name"],
                        "artist": track["artists"][0]["name"],
                        "album": track["album"]["name"],
                        "popularity": track["popularity"],
                    }
                )

            return tracks
        except Exception as e:
            logger.error(f"❌ Failed to search tracks: {e}")
            return []

    @spotify_throttle()
    def get_user_playlists(self, limit: int = 10) -> list:
        """
        Get the current user's playlists.

        Args:
            limit: Number of playlists to return (default: 10)

        Returns:
            list: List of playlist information dictionaries
        """
        if not self.is_authenticated or self._spotify is None:
            raise Exception("Client is not authenticated")

        try:
            results = self._spotify.current_user_playlists(limit=limit)
            if results is None or "items" not in results:
                logger.error("❌ No playlists found")
                return []

            playlists = []

            for playlist in results["items"]:
                playlists.append(
                    {
                        "id": playlist["id"],
                        "name": playlist["name"],
                        "description": playlist["description"],
                        "tracks_total": playlist["tracks"]["total"],
                        "public": playlist["public"],
                        "owner": playlist["owner"]["display_name"],
                    }
                )

            return playlists
        except Exception as e:
            logger.error(f"❌ Failed to get playlists: {e}")
            return []

    @spotify_throttle()
    def get_user_saved_tracks(self, limit: int = 10) -> list:
        """
        Get the current user's saved tracks (liked songs).

        Args:
            limit: Number of saved tracks to return (default: 10)

        Returns:
            list: List of saved track information dictionaries
        """
        if not self.is_authenticated or self._spotify is None:
            raise Exception("Client is not authenticated")

        try:
            results = self._spotify.current_user_saved_tracks(limit=limit)
            if results is None or "items" not in results:
                logger.error("❌ No saved tracks found")
                return []

            tracks = []

            for item in results["items"]:
                track = item["track"]
                tracks.append(
                    {
                        "id": track["id"],
                        "name": track["name"],
                        "artist": track["artists"][0]["name"],
                        "album": track["album"]["name"],
                        "added_at": item["added_at"],
                    }
                )

            return tracks
        except Exception as e:
            logger.error(f"❌ Failed to get saved tracks: {e}")
            return []
