"""
Automatic OAuth redirect capture using local HTTP server.
"""

import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional


class CallbackHTTPServer(HTTPServer):
    """Custom HTTP server with OAuth callback attributes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auth_code: str | None = None
        self.auth_error: str | None = None
        self.callback_received: bool = False


class AuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth callback."""

    server: CallbackHTTPServer  # Type hint for our custom server

    def do_GET(self):
        """Handle GET request to capture OAuth callback."""
        # Parse the query parameters from the URL
        parsed_url = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_url.query)

        # Store the authorization code or error
        if "code" in query_params:
            self.server.auth_code = query_params["code"][0]
            response_message = """
            <html>
            <body>
            <h1>✅ Authorization Successful!</h1>
            <p>You can close this window and return to your application.</p>
            <script>window.close();</script>
            </body>
            </html>
            """
            self.send_response(200)
        elif "error" in query_params:
            self.server.auth_error = query_params["error"][0]
            response_message = f"""
            <html>
            <body>
            <h1>❌ Authorization Failed</h1>
            <p>Error: {query_params["error"][0]}</p>
            <p>You can close this window.</p>
            </body>
            </html>
            """
            self.send_response(400)
        else:
            response_message = """
            <html>
            <body>
            <h1>❓ Unexpected Response</h1>
            <p>No authorization code or error found.</p>
            </body>
            </html>
            """
            self.send_response(400)

        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(response_message.encode())

        # Signal that we've received the callback
        self.server.callback_received = True

    def log_message(self, format, *args):
        """Suppress server logs."""
        pass


class AuthServer:
    """Local HTTP server for capturing OAuth callbacks."""

    def __init__(self, port: int = 8080):
        self.port = port
        self.server: Optional[CallbackHTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None

    def start(self) -> str:
        """
        Start the local server and return the callback URL.

        Returns:
            str: The callback URL to use in OAuth flow
        """
        self.server = CallbackHTTPServer(("localhost", self.port), AuthCallbackHandler)

        # Start server in a separate thread
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()

        callback_url = f"http://localhost:{self.port}/callback"
        print(f"🚀 Local auth server started at {callback_url}")
        return callback_url

    def wait_for_callback(
        self, timeout: int = 300
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Wait for the OAuth callback to be received.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            tuple: (auth_code, error) - one will be None
        """
        if not self.server:
            return None, "Server not started"

        import time

        start_time = time.time()

        while not self.server.callback_received:
            if time.time() - start_time > timeout:
                return None, "Timeout waiting for callback"
            time.sleep(0.1)

        return self.server.auth_code, self.server.auth_error

    def stop(self):
        """Stop the local server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.server_thread:
            self.server_thread.join()
        print("🛑 Local auth server stopped")
