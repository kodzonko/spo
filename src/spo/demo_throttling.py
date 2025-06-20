"""
Demo script to showcase the throttling mechanism for Spotify API calls.

This script demonstrates how the throttling decorator works by making multiple
API calls and showing the rate limiting in action.
"""

import time
from typing import List

from .spotify_client import SpotifyClient


def demo_throttling():
    """
    Demonstrate the throttling mechanism by making multiple API calls.

    This will show:
    - Rate limiting in action (delays between requests)
    - Retry behavior on 429 responses
    - Exponential backoff for failed requests
    """
    print("🚀 Starting Spotify API throttling demonstration...")
    print("=" * 60)

    try:
        # Initialize Spotify client
        with SpotifyClient() as client:
            print(f"✅ Authenticated as: {client.user_info}")
            print()

            # Test 1: Multiple search requests to demonstrate rate limiting
            print("📍 Test 1: Multiple search requests (rate limiting demo)")
            print("-" * 50)

            search_queries = [
                "Bohemian Rhapsody",
                "Billie Jean",
                "Hotel California",
                "Sweet Child O Mine",
                "Stairway to Heaven",
            ]

            start_time = time.time()

            for i, query in enumerate(search_queries, 1):
                print(f"🔍 Search {i}/5: '{query}'")
                request_start = time.time()

                tracks = client.search_tracks(query, limit=3)

                request_duration = time.time() - request_start

                if tracks:
                    print(
                        f"   ✅ Found {len(tracks)} tracks in {request_duration:.2f}s"
                    )
                    for track in tracks[:1]:  # Show only first result
                        print(f"      🎵 {track['name']} - {track['artist']}")
                else:
                    print(f"   ❌ No results in {request_duration:.2f}s")

                print()

            total_duration = time.time() - start_time
            print(f"⏱️  Total time for 5 searches: {total_duration:.2f}s")
            print(f"📊 Average time per request: {total_duration / 5:.2f}s")
            print()

            # Test 2: Get user data
            print("📍 Test 2: User data retrieval")
            print("-" * 50)

            print("📋 Getting user playlists...")
            playlists = client.get_user_playlists(limit=5)
            if playlists:
                print(f"   ✅ Found {len(playlists)} playlists")
                for playlist in playlists[:3]:
                    print(
                        f"      📁 {playlist['name']} ({playlist['tracks_total']} tracks)"
                    )
            else:
                print("   ❌ No playlists found")
            print()

            print("❤️  Getting saved tracks...")
            saved_tracks = client.get_user_saved_tracks(limit=5)
            if saved_tracks:
                print(f"   ✅ Found {len(saved_tracks)} saved tracks")
                for track in saved_tracks[:3]:
                    print(f"      🎵 {track['name']} - {track['artist']}")
            else:
                print("   ❌ No saved tracks found")
            print()

            # Test 3: Get detailed track info
            print("📍 Test 3: Detailed track information")
            print("-" * 50)

            if saved_tracks:
                track_id = saved_tracks[0]["id"]
                print(f"🔍 Getting details for track ID: {track_id}")

                track_info = client.get_track_info(track_id)
                if track_info:
                    print("   ✅ Track details retrieved:")
                    print(f"      🎵 Name: {track_info['name']}")
                    print(f"      👤 Artist: {track_info['artist']}")
                    print(f"      💿 Album: {track_info['album']}")
                    print(f"      📊 Popularity: {track_info['popularity']}/100")
                    if track_info["preview_url"]:
                        print(f"      🔗 Preview: Available")
                    else:
                        print(f"      🔗 Preview: Not available")
                else:
                    print("   ❌ Failed to get track details")
            else:
                print("   ⏭️  Skipping (no saved tracks available)")

            print()
            print("✅ Throttling demonstration completed!")
            print("=" * 60)
            print()
            print("🔧 Throttling Features Demonstrated:")
            print("   • Rate limiting (max 0.5 requests/second)")
            print("   • Burst handling (up to 5 requests)")
            print("   • Automatic retry on 429 responses")
            print("   • Exponential backoff with jitter")
            print("   • Graceful error handling")

    except Exception as e:
        print(f"❌ Demo failed: {e}")
        print("💡 Make sure you have valid Spotify credentials in your .env file")


def demo_rate_limit_simulation():
    """
    Simulate hitting rate limits to demonstrate retry behavior.

    Note: This is for educational purposes. In practice, the throttling
    should prevent hitting rate limits in the first place.
    """
    print("🚀 Starting rate limit simulation...")
    print("⚠️  This demo makes rapid API calls to demonstrate retry behavior")
    print("=" * 60)

    try:
        with SpotifyClient() as client:
            print(f"✅ Authenticated as: {client.user_info}")
            print()

            # Make rapid requests to potentially trigger rate limiting
            rapid_queries = ["test"] * 10  # 10 identical searches

            print("🔄 Making 10 rapid search requests...")
            start_time = time.time()

            for i, query in enumerate(rapid_queries, 1):
                print(f"   Request {i:2d}/10: ", end="", flush=True)
                request_start = time.time()

                try:
                    tracks = client.search_tracks(f"{query} {i}", limit=1)
                    request_duration = time.time() - request_start
                    print(f"✅ Success ({request_duration:.2f}s)")

                except Exception as e:
                    request_duration = time.time() - request_start
                    print(f"❌ Failed ({request_duration:.2f}s): {e}")

            total_duration = time.time() - start_time
            print()
            print(f"⏱️  Total time: {total_duration:.2f}s")
            print(f"📊 Average time per request: {total_duration / 10:.2f}s")

    except Exception as e:
        print(f"❌ Simulation failed: {e}")


if __name__ == "__main__":
    print("🎵 Spotify API Throttling Demo")
    print("Choose a demo:")
    print("1. Basic throttling demonstration")
    print("2. Rate limit simulation")
    print()

    choice = input("Enter choice (1 or 2): ").strip()

    if choice == "1":
        demo_throttling()
    elif choice == "2":
        demo_rate_limit_simulation()
    else:
        print("Invalid choice. Running basic demo...")
        demo_throttling()
