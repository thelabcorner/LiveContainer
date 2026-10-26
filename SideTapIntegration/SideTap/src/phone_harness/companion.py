"""Explicit HTTPS companion for SideTap's *existing* Windows viewer.

Only run this after the user chooses to pair their LiveContainer SideTap UI.
The original SideTap viewer remains bound to PC loopback. This TLS proxy
enforces an independent pairing token, an ephemeral secure HttpOnly cookie,
same-origin checks and a fixed backend. No iPhone IPA/install needed.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import hmac
import html
import http.client
import ipaddress
import json
import secrets
import socket
import ssl
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config

DEFAULT_PORT = 8781
MAX_BODY = 12 * 1024 * 1024
MAX_REPLY = 32 * 1024 * 1024


def _certificate(state: Path, address: str) -> tuple[Path, Path, str]:
    """Generate a persistent, random self-signed TLS leaf; pin out-of-band."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    state.mkdir(parents=True, exist_ok=True)
    certfile, keyfile = state / "companion.crt", state / "companion.key"
    if certfile.exists() != keyfile.exists():
        raise RuntimeError("Companion TLS certificate/key pair is incomplete; refusing to rotate trust")
    if not certfile.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SideTap Companion")]))
                .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SideTap Companion")]))
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=2))
                .not_valid_after(now + datetime.timedelta(days=365))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(address))]), critical=False)
                .sign(key, hashes.SHA256()))
        keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                              serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
        try:
            keyfile.chmod(0o600)
        except OSError:
            pass
        certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    cert = x509.load_pem_x509_certificate(certfile.read_bytes())
    return certfile, keyfile, hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def _pair_token(state: Path) -> str:
    state.mkdir(parents=True, exist_ok=True)
    path = state / "companion-pair-token"
    if path.is_file():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) < 32:
            raise RuntimeError("Existing pairing secret is too short; refusing to use it")
        return token
    token = secrets.token_urlsafe(32)
    with path.open("x", encoding="utf-8") as file:
        file.write(token)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def _login_page() -> bytes:
    return b"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SideTap - pair this device</title>
<style>*{box-sizing:border-box}body{background:#101418;color:#e8edf2;
font:16px system-ui,sans-serif;min-height:100vh;display:grid;place-items:center;margin:0;padding:24px}
main{max-width:440px;width:100%}h1{font-size:32px}p{color:#b9c6d2;line-height:1.5}
input,button{width:100%;border-radius:10px;padding:14px;font:inherit}
input{border:1px solid #64748b;background:#222b36;color:white}
button{background:#4493f8;border:0;margin-top:14px;font-weight:700}
</style></head><body><main><h1>SideTap</h1>
<p>Enter the pairing code displayed by SideTap on your Windows workstation.
This connection is end-to-end encrypted and pinned to your workstation's TLS certificate.</p>
<form action="/pair" method="post">
<label for="code">Pairing code</label>
<input id="code" name="code" type="password" autocomplete="off" required>
<button type="submit">Connect SideTap</button></form></main></body></html>"""


class CompanionHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 40

    def log_message(self, *_args):
        pass  # Never record passwords, session cookies, phone contents or path secrets.

    def _send(self, code: int, body: bytes, content_type="text/plain; charset=utf-8",
              extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _origin_ok(self, for_post=False) -> bool:
        base = self.server.base_url
        if self.headers.get("Host") != self.server.authority:
            return False
        origin = self.headers.get("Origin")
        if origin and origin != base:
            return False
        if for_post and origin != base:
            return False
        return self.headers.get("Sec-Fetch-Site", "none") in ("same-origin", "none")

    def _authenticated(self) -> bool:
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except Exception:
            return False
        value = jar.get("SideTapSession")
        return bool(value and hmac.compare_digest(value.value, self.server.session_secret))

    def _proxy(self, method: str, body: bytes = b"") -> None:
        # No arbitrary URLs, localhost SSRF, encoded paths, or unbounded responses.
        path = self.path.split("?", 1)[0]
        if path != "/" and not (path.startswith("/api/") and "%" not in path and ".." not in path):
            self._send(404, b"not found")
            return
        if method == "POST" and not path.startswith("/api/"):
            self._send(405, b"method not allowed")
            return
        headers = {"Host": f"127.0.0.1:{config.VIEWER_PORT}"}
        if method == "POST":
            headers["Content-Type"] = "application/json"
        try:
            conn = http.client.HTTPConnection("127.0.0.1", config.VIEWER_PORT, timeout=35)
            try:
                conn.request(method, path, body=body or None, headers=headers)
                response = conn.getresponse()
                payload = response.read(MAX_REPLY + 1)
                if len(payload) > MAX_REPLY:
                    self._send(502, b"viewer response too large")
                    return
                kind = response.getheader("Content-Type", "application/octet-stream")
                if path == "/api/status" and response.status == 200:
                    data = json.loads(payload)
                    # MJPEG uses a *different unprotected port*. Hide it so the
                    # real SideTap viewer falls back to same-origin screenshots.
                    data["mjpeg"] = None
                    payload = json.dumps(data).encode("utf-8")
                    kind = "application/json"
                self._send(response.status, payload, kind)
            finally:
                conn.close()
        except (OSError, http.client.HTTPException, ValueError) as exc:
            self._send(502, b"SideTap Windows viewer not reachable")

    def do_GET(self) -> None:
        if not self._origin_ok():
            self._send(403, b"forbidden")
        elif not self._authenticated():
            self._send(200, _login_page(), "text/html; charset=utf-8",
                       {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"})
        else:
            self._proxy("GET")

    def do_POST(self) -> None:
        if not self._origin_ok(for_post=True):
            self._send(403, b"forbidden")
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if self.headers.get("Transfer-Encoding") or not 0 <= length <= MAX_BODY:
            self.close_connection = True
            self._send(413, b"invalid body length")
            return
        if self.path == "/pair":
            if length > 4096 or self.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded":
                self._send(400, b"invalid pairing request")
                return
            from urllib.parse import parse_qs
            fields = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            token = fields.get("code", [""])[0]
            if not hmac.compare_digest(token, self.server.pair_token):
                self._send(403, b"invalid pairing code")
                return
            self._send(303, b"", extra={"Location": "/", "Set-Cookie": (
                f"SideTapSession={self.server.session_secret}; Secure; HttpOnly; SameSite=Strict; Path=/")})
            return
        if not self._authenticated():
            self.close_connection = True
            self._send(401, b"pairing required")
            return
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            self.close_connection = True
            self._send(415, b"JSON required")
            return
        self._proxy("POST", self.rfile.read(length))


class CompanionServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: str, port: int, token: str):
        super().__init__((address, port), CompanionHandler)
        self.pair_token = token
        self.session_secret = secrets.token_urlsafe(32)
        self.authority = f"{address}:{port}"
        self.base_url = f"https://{self.authority}"


def _viewer_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", config.VIEWER_PORT), timeout=1):
            return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in encrypted SideTap viewer for LiveContainer")
    parser.add_argument("--bind", default="127.0.0.1", help="Explicit PC LAN IPv4 address, never 0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    ip = ipaddress.ip_address(args.bind)
    if ip.version != 4 or not (ip.is_private or ip.is_loopback) or ip.is_unspecified or ip.is_multicast:
        parser.error("Bind to one specific private/LAN IPv4 address; no public or wildcard binding")
    if not 1024 <= args.port <= 65535:
        parser.error("Invalid HTTPS port")

    state = config.STATE_DIR
    cert, key, fingerprint = _certificate(state, args.bind)
    token = _pair_token(state)
    if not _viewer_reachable():
        from . import viewer
        threading.Thread(target=viewer.serve, kwargs={"open_browser": False}, daemon=True).start()

    server = CompanionServer(args.bind, args.port, token)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"SideTap iPhone app: https://{args.bind}:{args.port}/", flush=True)
    print(f"Certificate SHA-256: {fingerprint}", flush=True)
    print(f"Pairing code (keep private): {token}", flush=True)
    print("This service exposes phone control only after explicit TLS-pinned pairing. Ctrl+C stops it.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
