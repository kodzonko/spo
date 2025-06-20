import pytest
import requests

from spo.auth_server import AuthServer


@pytest.fixture
def auth_server():
    server = AuthServer(port=8081)
    url = server.start()
    yield server, url
    server.stop()


def test_start_returns_callback_url(auth_server):
    server, url = auth_server
    assert url == "http://localhost:8081/callback"


def test_callback_with_code(auth_server):
    server, url = auth_server
    # Simulate OAuth provider redirect with code
    callback_url = f"{url}?code=testcode123"
    resp = requests.get(callback_url)
    assert resp.status_code == 200
    assert "Authorization Successful" in resp.text

    code, error = server.wait_for_callback(timeout=2)
    assert code == "testcode123"
    assert error is None


def test_callback_with_error(auth_server):
    server, url = auth_server
    callback_url = f"{url}?error=access_denied"
    resp = requests.get(callback_url)
    assert resp.status_code == 400
    assert "Authorization Failed" in resp.text

    code, error = server.wait_for_callback(timeout=2)
    assert code is None
    assert error == "access_denied"


def test_callback_with_no_params(auth_server):
    server, url = auth_server
    callback_url = url  # No query params
    resp = requests.get(callback_url)
    assert resp.status_code == 400
    assert "Unexpected Response" in resp.text

    code, error = server.wait_for_callback(timeout=2)
    assert code is None
    assert error is None


def test_non_callback_path_returns_501(auth_server):
    server, url = auth_server
    # Use a different path to trigger the 501 branch
    resp = requests.get("http://localhost:8081/not_callback")
    assert resp.status_code == 501


def test_wait_for_callback_server_not_started():
    server = AuthServer(port=8090)
    # Do not start the server
    code, error = server.wait_for_callback(timeout=1)
    assert code is None
    assert error == "Server not started"


def test_wait_for_callback_timeout():
    server = AuthServer(port=8082)
    server.start()
    try:
        code, error = server.wait_for_callback(timeout=1)
        assert code is None
        assert error == "Timeout waiting for callback"
    finally:
        server.stop()
