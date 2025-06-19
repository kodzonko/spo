import marimo

__generated_with = "0.11.2"
app = marimo.App(width="medium")


@app.cell
def _():
    return


@app.cell
def _():
    import asyncio
    import os
    from pprint import pprint

    import spotipy
    from dotenv import load_dotenv
    from spotipy.oauth2 import SpotifyOAuth

    load_dotenv()

    def get_user_playlists():
        # Set up your credentials
        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        redirect_uri = "https://spotify.com/"  # Simplified redirect URI

        if not client_id or not client_secret:
            raise ValueError(
                "Please set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET environment variables"
            )

        # Define the required scopes
        scope = "playlist-read-private playlist-read-collaborative"

        try:
            # Initialize the Spotify client with authentication
            sp = spotipy.Spotify(
                auth_manager=SpotifyOAuth(
                    client_id=client_id,
                    client_secret=client_secret,
                    redirect_uri=redirect_uri,
                    scope=scope,
                )
            )

            # Test the connection
            sp.current_user()
        except Exception as e:
            print(
                f"Authentication failed. Please check your credentials and redirect URI."
            )
            print(f"Error details: {str(e)}")
            return None

        # Fetch all playlists
        playlists = []
        offset = 0
        limit = 50  # Maximum allowed by Spotify API

        while True:
            results = sp.current_user_playlists(limit=limit, offset=offset)
            if not results["items"]:
                break

            for playlist in results["items"]:
                playlist_info = {
                    "name": playlist["name"],
                    "id": playlist["id"],
                    "tracks_total": playlist["tracks"]["total"],
                    "owner": playlist["owner"]["display_name"],
                    "public": playlist["public"],
                    "url": playlist["external_urls"]["spotify"],
                }
                playlists.append(playlist_info)

            offset += limit

            if len(results["items"]) < limit:
                break

        return playlists

    return (
        SpotifyOAuth,
        asyncio,
        get_user_playlists,
        load_dotenv,
        os,
        pprint,
        spotipy,
    )


@app.cell
def _(get_user_playlists):
    get_user_playlists()
    return


if __name__ == "__main__":
    app.run()
