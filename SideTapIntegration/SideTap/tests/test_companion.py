"""Offline security and proxy integration tests: never talk to a real iPhone."""
from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from phone_harness import companion


class DummyViewer(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        data = (json.dumps({"mjpeg": 9100, "window": {"width": 393, "height": 852}}).encode()
                if self.path == "/api/status" else b"<html>Actual SideTap viewer</html>")
        self.send_response(200)
        self.send_header("Content-Type", "application/json" if self.path == "/api/status" else "text/html")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        content = json.dumps({"received": json.loads(body), "host": self.headers["Host"]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


@pytest.fixture
def companion_fixture(monkeypatch):
    backend = ThreadingHTTPServer(("127.0.0.1", 0), DummyViewer)
    monkeypatch.setattr(companion.config, "VIEWER_PORT", backend.server_port)
    outer = companion.CompanionServer("127.0.0.1", 0, "known-pairing-code-" + "A" * 25)
    port = outer.server_port
    outer.authority = f"127.0.0.1:{port}"
    outer.base_url = f"https://127.0.0.1:{port}"
    threads = [
        threading.Thread(target=backend.serve_forever, daemon=True),
        threading.Thread(target=outer.serve_forever, daemon=True),
    ]
    for thread in threads: thread.start()
    yield port, outer.pair_token, outer.base_url
    outer.shutdown(); backend.shutdown()
    outer.server_close(); backend.server_close()
    for thread in threads: thread.join(timeout=2)


def ask(port, method, path, body=b"", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request(method, path, body=body, headers=headers or {})
    res = conn.getresponse()
    data = res.read()
    status = res.status
    returned = dict(res.getheaders())
    conn.close()
    return status, returned, data


def test_unpaired_get_returns_login_not_control_ui(companion_fixture):
    port, token, url = companion_fixture
    status, headers, data = ask(port, "GET", "/")
    assert status == 200 and b"Pairing code" in data
    assert b"Actual SideTap viewer" not in data
    assert "none" in headers["Content-Security-Policy"]


def test_wrong_host_rejected(companion_fixture):
    port, token, url = companion_fixture
    status, _, _ = ask(port, "GET", "/", headers={"Host": "evil.example"})
    assert status == 403


def test_cross_origin_pairing_rejected(companion_fixture):
    port, token, url = companion_fixture
    status, _, _ = ask(port, "POST", "/pair", body=("code=" + token).encode(),
                       headers={"Origin": "https://evil.example", "Content-Type": "application/x-www-form-urlencoded"})
    assert status == 403


def test_invalid_pairing_rejected(companion_fixture):
    port, token, url = companion_fixture
    status, headers, _ = ask(port, "POST", "/pair", body=b"code=wrong",
                             headers={"Origin": url, "Content-Type": "application/x-www-form-urlencoded"})
    assert status == 403 and "Set-Cookie" not in headers


def pair(port, token, url):
    from urllib.parse import urlencode
    status, headers, _ = ask(port, "POST", "/pair", body=urlencode({"code": token}).encode(),
                             headers={"Origin": url, "Content-Type": "application/x-www-form-urlencoded"})
    assert status == 303 and headers["Location"] == "/"
    assert "Secure" in headers["Set-Cookie"] and "HttpOnly" in headers["Set-Cookie"]
    assert "SameSite=Strict" in headers["Set-Cookie"]
    return headers["Set-Cookie"].split(";", 1)[0]


def test_authenticated_proxy_returns_actual_viewer_and_safe_status(companion_fixture):
    port, token, url = companion_fixture
    cookie = pair(port, token, url)
    status, _, data = ask(port, "GET", "/", headers={"Cookie": cookie})
    assert status == 200 and b"Actual SideTap viewer" in data
    status, _, data = ask(port, "GET", "/api/status", headers={"Cookie": cookie})
    status_obj = json.loads(data)
    assert status == 200 and status_obj["mjpeg"] is None
    assert status_obj["window"]["height"] == 852


def test_authenticated_action_uses_loopback_backend_only(companion_fixture):
    port, token, url = companion_fixture
    cookie = pair(port, token, url)
    status, _, body = ask(port, "POST", "/api/tap", body=b'{"x":123}',
                          headers={"Cookie": cookie, "Origin": url, "Content-Type": "application/json"})
    result = json.loads(body)
    assert status == 200 and result["received"]["x"] == 123
    assert result["host"].startswith("127.0.0.1:")


def test_post_without_pairing_denied(companion_fixture):
    port, token, url = companion_fixture
    status, _, _ = ask(port, "POST", "/api/tap", body=b'{"x":123}',
                        headers={"Origin": url, "Content-Type": "application/json"})
    assert status == 401


def test_post_cross_origin_denied_even_with_session(companion_fixture):
    port, token, url = companion_fixture
    cookie = pair(port, token, url)
    status, _, _ = ask(port, "POST", "/api/tap", body=b'{"x":123}',
                        headers={"Cookie": cookie, "Origin": "https://evil.example", "Content-Type": "application/json"})
    assert status == 403


def test_unknown_api_and_encoded_paths_denied(companion_fixture):
    port, token, url = companion_fixture
    cookie = pair(port, token, url)
    for path in ("/private", "/api/%2e%2e/secrets", "/api/../secret"):
        status, _, _ = ask(port, "GET", path, headers={"Cookie": cookie})
        assert status == 404


def test_certificate_is_persistent_and_reused(tmp_path):
    path1, key1, hash1 = companion._certificate(tmp_path, "127.0.0.1")
    bytes1 = path1.read_bytes()
    path2, key2, hash2 = companion._certificate(tmp_path, "127.0.0.1")
    assert (path1, key1, hash1) == (path2, key2, hash2)
    assert bytes1 == path1.read_bytes()
    assert len(hash1) == 64


def test_pair_token_reused_not_rotated(tmp_path):
    a = companion._pair_token(tmp_path)
    b = companion._pair_token(tmp_path)
    assert a == b and len(a) >= 32

def test_real_tls_handshake_matches_pinned_fingerprint(tmp_path):
    """The TLS endpoint must serve the exact cert printed for iOS pairing."""
    import hashlib
    import ssl
    import socket
    cert, key, pinned = companion._certificate(tmp_path, "127.0.0.1")
    server = companion.CompanionServer("127.0.0.1", 0, "pairing-secret-" + "B" * 32)
    port = server.server_port
    server.authority = f"127.0.0.1:{port}"
    server.base_url = f"https://127.0.0.1:{port}"
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(str(cert), str(key))
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Test client bypasses CA trust *only* to inspect and verify the pinned
        # leaf. Production iOS WebKit uses the explicit SHA256 equality gate.
        client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        client_context.check_hostname = False
        client_context.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection("127.0.0.1", port, context=client_context, timeout=3)
        conn.connect()
        leaf = conn.sock.getpeercert(binary_form=True)
        assert hashlib.sha256(leaf).hexdigest() == pinned
        conn.request("GET", "/", headers={"Host": f"127.0.0.1:{port}"})
        res = conn.getresponse()
        assert res.status == 200 and b"SideTap" in res.read()
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
