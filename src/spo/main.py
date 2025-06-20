"""
Spotify authentication module using Authorization Code Flow.
"""

import os
from typing import Optional

import spotipy  # type: ignore
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth  # type: ignore


class SpotifyClient:
    """
    Spotify API client with built-in authentication using Authorization Code Flow.

    This client handles authentication automatically during initialization and provides
    convenient methods for interacting with the Spotify Web API.
    """

    def __init__(self) -> None:
        """
        Initialize the Spotify client with authentication.

        Raises:
            ValueError: If required environment variables are missing
            Exception: If authentication fails
        """
        self._spotify: Optional[spotipy.Spotify] = None
        self._scopes = "user-library-read playlist-read-private user-read-private"
        self._cache_path = ".spo_cache"
        self._user: Optional[dict] = None
        self._authenticate()

    def _authenticate(self) -> None:
        """
        Authenticate with Spotify using Authorization Code Flow.

        This authentication method allows access to user-specific data by requesting
        user authorization through a web browser. The user will be redirected to
        Spotify's authorization page to grant permissions.

        Raises:
            ValueError: If required environment variables are missing
            Exception: If authentication fails
        """
        # Load environment variables from .env file
        load_dotenv()

        # Get credentials from environment variables
        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "https://spotify.com/")

        # Validate that credentials are present
        if not client_id or not client_secret:
            raise ValueError(
                "Missing Spotify credentials. Please ensure SPOTIFY_CLIENT_ID and "
                "SPOTIFY_CLIENT_SECRET are set in your .env file."
            )

        try:
            # Create OAuth manager for Authorization Code Flow
            auth_manager = SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=self._scopes,
                cache_path=self._cache_path,
            )

            # Create authenticated Spotify client
            self._spotify = spotipy.Spotify(auth_manager=auth_manager)

            # Test the connection by making a simple API call
            self._user = self._spotify.current_user()

            if self._user is None:
                raise Exception("Failed to get user information")

            print(
                f"✅ Successfully authenticated with Spotify API using Authorization Code Flow"
            )
            print(
                f"👤 Logged in as: {self._user['display_name']} (@{self._user['id']})"
            )

        except Exception as e:
            print(f"❌ Failed to authenticate with Spotify API: {e}")
            raise

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
                print("❌ Track not found")
                return {}

            return {
                "name": track["name"],
                "artist": track["artists"][0]["name"],
                "album": track["album"]["name"],
                "popularity": track["popularity"],
                "preview_url": track["preview_url"],
            }
        except Exception as e:
            print(f"❌ Failed to get track info: {e}")
            return {}

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
                print("❌ No search results found")
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
            print(f"❌ Failed to search tracks: {e}")
            return []

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
                print("❌ No playlists found")
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
            print(f"❌ Failed to get playlists: {e}")
            return []

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
                print("❌ No saved tracks found")
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
            print(f"❌ Failed to get saved tracks: {e}")
            return []

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup if needed."""
        # Could add cleanup logic here if needed
        pass


def main():
    """
    Main function to demonstrate the SpotifyClient class usage.
    """
    print("🎵 Spotify Authorization Code Flow Authentication Demo")
    print("=" * 55)
    print("📝 Note: This will open a browser window for user authorization")
    print()

    try:
        # Create Spotify client - authentication happens automatically
        with SpotifyClient() as client:
            print(f"\n👤 Authenticated as: {client.user_info}")

            print("\n🔍 Testing API with public data (search)...")

            # Example: Search for tracks (public data)
            tracks = client.search_tracks("The Beatles", limit=3)

            if tracks:
                print(f"\nFound {len(tracks)} tracks:")
                for i, track in enumerate(tracks, 1):
                    print(
                        f"{i}. {track['name']} by {track['artist']} (Popularity: {track['popularity']})"
                    )

            print("\n📚 Getting user's playlists...")

            # Example: Get user playlists (requires authorization)
            playlists = client.get_user_playlists(limit=5)

            if playlists:
                print(f"\nFound {len(playlists)} playlists:")
                for i, playlist in enumerate(playlists, 1):
                    print(
                        f"{i}. '{playlist['name']}' by {playlist['owner']} "
                        f"({playlist['tracks_total']} tracks)"
                    )

            print("\n❤️ Getting user's saved tracks...")

            # Example: Get saved tracks (requires authorization)
            saved_tracks = client.get_user_saved_tracks(limit=5)

            if saved_tracks:
                print(f"\nFound {len(saved_tracks)} saved tracks:")
                for i, track in enumerate(saved_tracks, 1):
                    print(f"{i}. {track['name']} by {track['artist']}")
            else:
                print("No saved tracks found or you haven't liked any songs yet.")

    except ValueError as e:
        print(f"❌ Configuration error: {e}")
    except Exception as e:
        print(f"❌ Authentication failed: {e}")


if __name__ == "__main__":
    main()
