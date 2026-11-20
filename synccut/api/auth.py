"""Desktop account recovery and Google OAuth helpers."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import smtplib
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, HTTPServer

from synccut.api import db

logger = logging.getLogger(__name__)
GOOGLE_FLOW_TTL_SECONDS = 180
_GOOGLE_FLOWS: dict[str, dict] = {}
_GOOGLE_FLOWS_LOCK = threading.Lock()


class GoogleAuthConfigurationError(RuntimeError):
    pass


class EmailConfigurationError(RuntimeError):
    pass


def _set_google_flow_result(flow_id: str, result: dict) -> None:
    with _GOOGLE_FLOWS_LOCK:
        flow = _GOOGLE_FLOWS.get(flow_id)
        if flow is not None and flow["status"] == "pending":
            flow.update(result)


def _verify_google_response(code: str, verifier: str, redirect_uri: str, client_id: str) -> dict:
    params = {
        "code": code,
        "code_verifier": verifier,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if client_secret:
        params["client_secret"] = client_secret

    request_data = urllib.parse.urlencode(params).encode("ascii")
    token_request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=request_data,
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(token_request, timeout=20) as response:
        token_data = json.loads(response.read().decode("utf-8"))
    identity_token = token_data.get("id_token")
    if not identity_token:
        raise ValueError("Google did not return an ID token.")

    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    claims = id_token.verify_oauth2_token(identity_token, Request(), client_id)
    if not claims.get("email_verified") or not claims.get("sub") or not claims.get("email"):
        raise ValueError("Google account is missing a verified email address.")
    user = db.authenticate_google_user(
        str(claims["sub"]),
        str(claims["email"]),
        str(claims.get("name") or ""),
    )
    if user is None:
        raise ValueError("That email is connected to a different Google account.")
    token = user.pop("token")
    return {"status": "complete", "user": user, "token": token}


def start_google_signin() -> str:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    if not client_id:
        raise GoogleAuthConfigurationError(
            "Google sign-in is not configured. Set GOOGLE_CLIENT_ID for the desktop app."
        )

    flow_id = secrets.token_urlsafe(24)
    oauth_state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            received_state = query.get("state", [""])[0]
            if self.path.split("?", 1)[0] != "/" or not secrets.compare_digest(
                received_state, oauth_state
            ):
                page = b"Sign-in could not be verified. Return to SyncCut Studio."
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(page)
                return
            if query.get("error", [""])[0]:
                result = {"status": "error", "error": "Google sign-in was cancelled."}
                page = b"Sign-in was cancelled. Return to SyncCut Studio."
                self.send_response(200)
            else:
                try:
                    result = _verify_google_response(
                        query.get("code", [""])[0], verifier, redirect_uri, client_id
                    )
                    page = b"Sign-in complete. You can return to SyncCut Studio."
                    self.send_response(200)
                except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as error:
                    logger.warning("Google sign-in callback was rejected: %s", error)
                    result = {
                        "status": "error",
                        "error": "Google sign-in could not be verified. Check your connection and OAuth client configuration.",
                    }
                    page = b"Sign-in could not be completed. Return to SyncCut Studio."
                    self.send_response(400)
                except Exception:
                    logger.exception("Google sign-in callback failed.")
                    result = {
                        "status": "error",
                        "error": "Google sign-in could not be completed. Return to SyncCut Studio and try again.",
                    }
                    page = b"Sign-in could not be completed. Return to SyncCut Studio."
                    self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(page)
            _set_google_flow_result(flow_id, result)

        def log_message(self, _format, *_args):
            return

    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 1
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"
    auth_query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": oauth_state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{auth_query}"
    with _GOOGLE_FLOWS_LOCK:
        expired = [
            key for key, value in _GOOGLE_FLOWS.items()
            if value["expires_at"] <= time.monotonic()
        ]
        for key in expired:
            _GOOGLE_FLOWS.pop(key, None)
        if len(_GOOGLE_FLOWS) >= 5:
            server.server_close()
            raise GoogleAuthConfigurationError(
                "Too many Google sign-in attempts are already open. Finish or close one and try again."
            )
        _GOOGLE_FLOWS[flow_id] = {
            "status": "pending",
            "expires_at": time.monotonic() + GOOGLE_FLOW_TTL_SECONDS,
            "server": server,
        }

    def serve_callback():
        deadline = time.monotonic() + GOOGLE_FLOW_TTL_SECONDS
        try:
            while time.monotonic() < deadline:
                server.handle_request()
                with _GOOGLE_FLOWS_LOCK:
                    flow = _GOOGLE_FLOWS.get(flow_id)
                    if flow is None or flow["status"] != "pending":
                        break
            with _GOOGLE_FLOWS_LOCK:
                flow = _GOOGLE_FLOWS.get(flow_id)
                if flow is not None and flow["status"] == "pending":
                    flow.update(
                        status="error",
                        error="Google sign-in timed out. Please try again.",
                    )
        finally:
            server.server_close()

    threading.Thread(target=serve_callback, daemon=True).start()
    try:
        browser_opened = webbrowser.open(auth_url, new=2)
    except Exception:
        logger.exception("Could not open the system browser for Google sign-in.")
        browser_opened = False
    if not browser_opened:
        with _GOOGLE_FLOWS_LOCK:
            _GOOGLE_FLOWS.pop(flow_id, None)
        raise GoogleAuthConfigurationError(
            "Could not open your browser for Google sign-in. Check your default browser and try again."
        )
    return flow_id


def poll_google_signin(flow_id: str) -> dict:
    if not flow_id:
        return {"status": "error", "error": "Google sign-in session is missing."}
    with _GOOGLE_FLOWS_LOCK:
        flow = _GOOGLE_FLOWS.get(flow_id)
        if flow is None:
            return {"status": "error", "error": "Google sign-in expired. Please try again."}
        if flow["expires_at"] <= time.monotonic() and flow["status"] == "pending":
            flow.update(status="error", error="Google sign-in timed out. Please try again.")
        if flow["status"] == "pending":
            return {"status": "pending"}
        result = {key: value for key, value in flow.items() if key in {"status", "user", "token", "error"}}
        _GOOGLE_FLOWS.pop(flow_id, None)
        return result


def smtp_is_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST", "").strip() and os.environ.get("SMTP_FROM", "").strip())


def validate_smtp_configuration() -> None:
    if not smtp_is_configured():
        raise EmailConfigurationError(
            "Password recovery is not configured. Set SMTP_HOST and SMTP_FROM for the desktop app."
        )
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    if bool(username) != bool(password):
        raise EmailConfigurationError("Set both SMTP_USERNAME and SMTP_PASSWORD, or leave both blank.")
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
    except ValueError as error:
        raise EmailConfigurationError("SMTP_PORT must be a valid port number.") from error
    if not 1 <= port <= 65535:
        raise EmailConfigurationError("SMTP_PORT must be between 1 and 65535.")


def send_password_reset_email(email: str, reset_url: str, *, send_email: bool = True) -> None:
    host = os.environ.get("SMTP_HOST", "").strip()
    sender = os.environ.get("SMTP_FROM", "").strip()
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    validate_smtp_configuration()
    port = int(os.environ.get("SMTP_PORT", "587"))
    use_ssl = os.environ.get("SMTP_USE_SSL", "").strip().lower() in {"1", "true", "yes"}
    message = None
    if send_email:
        message = EmailMessage()
        message["Subject"] = "Reset your SyncCut Studio password"
        message["From"] = sender
        message["To"] = email
        message.set_content(
            "We received a request to reset your SyncCut Studio password.\n\n"
            f"Use this link within 30 minutes:\n{reset_url}\n\n"
            "If you did not request a reset, you can ignore this email."
        )
    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    smtp_kwargs = {"context": ssl.create_default_context()} if use_ssl else {}
    with smtp_class(host, port, timeout=15, **smtp_kwargs) as server:
        if not use_ssl:
            server.starttls(context=ssl.create_default_context())
        if username:
            server.login(username, password)
        if message is not None:
            server.send_message(message)


def new_password_reset_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    return token, token_hash


def password_reset_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=30)


def password_reset_url(token: str) -> str:
    base_url = os.environ.get(
        "SYNCCUT_RESET_URL",
        "http://127.0.0.1:5000/#/reset-password",
    ).rstrip("/")
    return f"{base_url}?token={urllib.parse.quote(token, safe='')}"
