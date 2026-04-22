#!/usr/bin/env python3
"""
Social Post Creator - Web UI

FastAPI backend for the content generation and approval workflow.
Calls tool functions directly (no subprocesses) for fast execution.

Usage:
    python app.py
    Then open http://localhost:8000 in your browser.

Requirements:
    pip install fastapi uvicorn python-multipart
"""

import asyncio
import json
import logging
import os
import secrets
import sqlite3
import smtplib
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime
from email.mime.text import MIMEText
from io import BytesIO
from pathlib import Path
from typing import Any, Dict

import bcrypt
import pyotp
import qrcode
import qrcode.image.pil
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pydantic import BaseModel

# Add tools directory to path so we can import directly
sys.path.insert(0, str(Path(__file__).parent / "tools"))

load_dotenv()

# ── Auth configuration ──────────────────────────────────────────────────────
def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_BOOTSTRAP_PASSWORD_HASH = os.getenv("AUTH_PASSWORD_HASH", "")
AUTH_BOOTSTRAP_TOTP_SECRET = os.getenv("TOTP_SECRET", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
AUTH_DB_PATH = Path(os.getenv("AUTH_DB_PATH", str(Path(__file__).parent / "data" / "auth.db")))
COOKIE_SECURE = env_flag("COOKIE_SECURE", False)
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("ALLOWED_ORIGIN", "").split(",") if origin.strip()]
ENABLE_DEBUG_API = env_flag("ENABLE_DEBUG_API", False)
AUTH_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "300"))
AUTH_RATE_LIMIT_MAX_ATTEMPTS = int(os.getenv("AUTH_RATE_LIMIT_MAX_ATTEMPTS", "5"))
AUTH_LOCKOUT_SECONDS = int(os.getenv("AUTH_LOCKOUT_SECONDS", "600"))

if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET must be set in .env")

serializer = URLSafeTimedSerializer(SESSION_SECRET)
SESSION_COOKIE = "session_token"
SESSION_MAX_AGE = 86400  # 24 hours
TOTP_ISSUER = "SocialPostCreator"

SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_APP_PASSWORD = os.getenv("SMTP_APP_PASSWORD", "")
BOOTSTRAP_ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

logger = logging.getLogger("auth")


class AuthStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_bootstrap_state()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS auth_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    password_hash TEXT NOT NULL DEFAULT '',
                    totp_secret TEXT NOT NULL DEFAULT '',
                    admin_email TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );

                INSERT OR IGNORE INTO auth_state (id, password_hash, totp_secret, admin_email, updated_at)
                VALUES (1, '', '', '', strftime('%s', 'now'));

                CREATE TABLE IF NOT EXISTS login_tokens (
                    token TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    pending_totp_secret TEXT NOT NULL DEFAULT '',
                    allow_reconfigure INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS reset_tokens (
                    token TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                """
            )
            conn.commit()

    def _migrate_bootstrap_state(self):
        state = self.get_auth_state()
        updates = {}
        if not state["password_hash"] and AUTH_BOOTSTRAP_PASSWORD_HASH:
            updates["password_hash"] = AUTH_BOOTSTRAP_PASSWORD_HASH
        if not state["totp_secret"] and AUTH_BOOTSTRAP_TOTP_SECRET:
            updates["totp_secret"] = AUTH_BOOTSTRAP_TOTP_SECRET
        if not state["admin_email"] and BOOTSTRAP_ADMIN_EMAIL:
            updates["admin_email"] = BOOTSTRAP_ADMIN_EMAIL
        if updates:
            with self._connect() as conn:
                set_clause = ", ".join(f"{key} = ?" for key in updates)
                values = list(updates.values())
                values.extend([time.time(), 1])
                conn.execute(f"UPDATE auth_state SET {set_clause}, updated_at = ? WHERE id = ?", values)
                conn.commit()

    def cleanup_expired_tokens(self):
        now = time.time()
        with self._connect() as conn:
            conn.execute("DELETE FROM login_tokens WHERE expires_at <= ?", (now,))
            conn.execute("DELETE FROM reset_tokens WHERE expires_at <= ?", (now,))
            conn.commit()

    def get_auth_state(self) -> Dict[str, str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT password_hash, totp_secret, admin_email FROM auth_state WHERE id = 1"
            ).fetchone()
        return {
            "password_hash": row["password_hash"] if row else "",
            "totp_secret": row["totp_secret"] if row else "",
            "admin_email": row["admin_email"] if row else "",
        }

    def get_password_hash(self) -> str:
        return self.get_auth_state()["password_hash"]

    def set_password_hash(self, password_hash: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE auth_state SET password_hash = ?, updated_at = ? WHERE id = 1",
                (password_hash, time.time()),
            )
            conn.commit()

    def get_totp_secret(self) -> str:
        return self.get_auth_state()["totp_secret"]

    def set_totp_secret(self, secret: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE auth_state SET totp_secret = ?, updated_at = ? WHERE id = 1",
                (secret, time.time()),
            )
            conn.commit()

    def clear_totp_secret(self):
        self.set_totp_secret("")

    def has_totp_secret(self) -> bool:
        return bool(self.get_totp_secret())

    def get_admin_email(self) -> str:
        return self.get_auth_state()["admin_email"]

    def create_login_token(self, username: str, allow_reconfigure: bool = False) -> str:
        self.cleanup_expired_tokens()
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO login_tokens (token, username, created_at, expires_at, allow_reconfigure)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token, username, now, now + 300, 1 if allow_reconfigure else 0),
            )
            conn.commit()
        return token

    def get_login_token(self, token: str) -> dict | None:
        self.cleanup_expired_tokens()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM login_tokens WHERE token = ?", (token,)).fetchone()
        return dict(row) if row else None

    def get_or_create_pending_totp_secret(self, token: str) -> str | None:
        entry = self.get_login_token(token)
        if not entry:
            return None
        if entry["pending_totp_secret"]:
            return entry["pending_totp_secret"]
        secret = pyotp.random_base32()
        with self._connect() as conn:
            conn.execute("UPDATE login_tokens SET pending_totp_secret = ? WHERE token = ?", (secret, token))
            conn.commit()
        return secret

    def delete_login_token(self, token: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM login_tokens WHERE token = ?", (token,))
            conn.commit()

    def create_reset_token(self) -> str:
        self.cleanup_expired_tokens()
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO reset_tokens (token, created_at, expires_at) VALUES (?, ?, ?)",
                (token, now, now + 900),
            )
            conn.commit()
        return token

    def verify_reset_token(self, token: str) -> bool:
        self.cleanup_expired_tokens()
        with self._connect() as conn:
            row = conn.execute("SELECT token FROM reset_tokens WHERE token = ?", (token,)).fetchone()
        return bool(row)

    def consume_reset_token(self, token: str) -> bool:
        self.cleanup_expired_tokens()
        with self._connect() as conn:
            row = conn.execute("SELECT token FROM reset_tokens WHERE token = ?", (token,)).fetchone()
            if not row:
                return False
            conn.execute("DELETE FROM reset_tokens WHERE token = ?", (token,))
            conn.commit()
        return True


class AuthRateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._entries: Dict[str, Dict[str, Any]] = {}

    def _prune(self, entry: Dict[str, Any], now: float):
        entry["failures"] = [ts for ts in entry.get("failures", []) if now - ts <= AUTH_RATE_LIMIT_WINDOW_SECONDS]
        if entry.get("locked_until", 0) <= now:
            entry["locked_until"] = 0

    def is_blocked(self, key: str) -> int:
        now = time.time()
        with self._lock:
            entry = self._entries.setdefault(key, {"failures": [], "locked_until": 0})
            self._prune(entry, now)
            if entry["locked_until"] > now:
                return int(entry["locked_until"] - now)
            return 0

    def record_failure(self, key: str):
        now = time.time()
        with self._lock:
            entry = self._entries.setdefault(key, {"failures": [], "locked_until": 0})
            self._prune(entry, now)
            entry["failures"].append(now)
            if len(entry["failures"]) >= AUTH_RATE_LIMIT_MAX_ATTEMPTS:
                entry["failures"].clear()
                entry["locked_until"] = now + AUTH_LOCKOUT_SECONDS

    def reset(self, key: str):
        with self._lock:
            self._entries.pop(key, None)


auth_store = AuthStore(AUTH_DB_PATH)
auth_rate_limiter = AuthRateLimiter()


def create_session_cookie(username: str) -> str:
    return serializer.dumps({"user": username, "nonce": secrets.token_hex(8)})


def verify_session_cookie(token: str) -> dict | None:
    try:
        return serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def request_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit_key(action: str, request: Request, subject: str = "") -> str:
    return f"{action}:{request_ip(request)}:{subject.strip().lower()}"


def check_rate_limit(action: str, request: Request, subject: str = "") -> JSONResponse | None:
    key = rate_limit_key(action, request, subject)
    remaining = auth_rate_limiter.is_blocked(key)
    if remaining > 0:
        minutes = max(1, remaining // 60)
        return JSONResponse(
            {"detail": f"Too many attempts. Please wait about {minutes} minute(s) and try again."},
            status_code=429,
        )
    return None


def record_rate_limit_failure(action: str, request: Request, subject: str = ""):
    auth_rate_limiter.record_failure(rate_limit_key(action, request, subject))


def reset_rate_limit(action: str, request: Request, subject: str = ""):
    auth_rate_limiter.reset(rate_limit_key(action, request, subject))


def cookie_should_be_secure(request: Request) -> bool:
    if COOKIE_SECURE:
        return True
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded_proto.lower() == "https"


def send_email(to: str, subject: str, body: str) -> bool:
    if not SMTP_EMAIL or not SMTP_APP_PASSWORD:
        logger.error("SMTP not configured — cannot send email")
        return False
    try:
        msg = MIMEText(body, "html")
        msg["Subject"] = subject
        msg["From"] = SMTP_EMAIL
        msg["To"] = to
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_EMAIL, SMTP_APP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def current_password_hash() -> str:
    return auth_store.get_password_hash()


def current_totp_secret() -> str:
    return auth_store.get_totp_secret()


def current_admin_email() -> str:
    return auth_store.get_admin_email()


def update_password_hash(new_hash: str):
    auth_store.set_password_hash(new_hash)


def save_totp_secret(secret: str):
    auth_store.set_totp_secret(secret)
    logger.info("2FA setup completed and persisted to durable auth storage.")


# ── App setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="Social Post Creator")
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=True,
    )

AUTH_EXEMPT = {"/login", "/auth/login", "/auth/verify-2fa", "/auth/setup-2fa-qr", "/auth/setup-2fa-secret", "/auth/logout",
               "/auth/forgot-password", "/reset-password", "/auth/reset-password"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in AUTH_EXEMPT or path.startswith("/static/"):
        return await call_next(request)
    token = request.cookies.get(SESSION_COOKIE)
    session_data = verify_session_cookie(token) if token else None
    if not session_data:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Your session expired. Please sign in again."}, status_code=401)
        return RedirectResponse(url="/login", status_code=302)
    request.state.user = session_data["user"]
    return await call_next(request)


# ── In-memory state ──────────────────────────────────────────────────────────
sessions: Dict[str, Dict] = {}
event_queues: Dict[str, asyncio.Queue] = {}


def new_session(topic: str) -> str:
    sid = str(uuid.uuid4())
    sessions[sid] = {
        "id": sid,
        "topic": topic,
        "workflow_status": "idle",
        "posts": {
            p: {"content": "", "hashtags": [], "status": "pending"}
            for p in ["linkedin", "facebook", "instagram"]
        },
        "image": {"url": None, "status": "pending"},
        "posting_results": {},
        "cancelled": False,
        "error": None,
        "log": [],
    }
    event_queues[sid] = asyncio.Queue()
    return sid


def push_event(sid: str, event_type: str, data: Any):
    if sid in event_queues:
        event_queues[sid].put_nowait({"type": event_type, "data": data})


def log(sid: str, msg: str):
    sessions[sid]["log"].append(msg)
    push_event(sid, "log", {"message": msg})


def is_cancelled(sid: str) -> bool:
    """Check if the workflow has been cancelled."""
    return sessions.get(sid, {}).get("cancelled", False)


def check_cancelled(sid: str):
    """Raise if the workflow was cancelled, so background workers stop."""
    if is_cancelled(sid):
        raise asyncio.CancelledError("Workflow stopped by user")


# ── Tool wrappers (run blocking I/O in thread pool) ───────────────────────────

async def _research(topic: str) -> Dict:
    """Run research_trends in a thread so it doesn't block the event loop."""
    from research_trends import research_trends
    return await asyncio.to_thread(research_trends, topic, 5)


async def _generate_content(topic: str, trends: Dict) -> Dict:
    """Run generate_posts in a thread."""
    from generate_content import generate_posts
    trends_context = f"Topic: {trends.get('topic', topic)}\n\nSummary: {trends.get('summary', '')}\n\nKey Insights:\n"
    for i, insight in enumerate(trends.get('insights', []), 1):
        trends_context += f"\n{i}. {insight.get('title', '')}\n{insight.get('content', '')[:500]}\n"
    return await asyncio.to_thread(generate_posts, topic, trends_context)


async def _revise_content(posts_dict: Dict, feedback: str) -> Dict:
    """Run revise_posts in a thread."""
    from revise_content import revise_posts
    return await asyncio.to_thread(revise_posts, posts_dict, feedback)


async def _generate_image_prompt(posts_dict: Dict, style: str = "") -> str:
    """Run generate_image_prompt in a thread."""
    from generate_image_prompt import generate_image_prompt
    return await asyncio.to_thread(generate_image_prompt, posts_dict, style or "modern professional")


async def _generate_image(prompt: str) -> bytes:
    """Run generate_image in a thread."""
    from generate_image import generate_image
    api_token = os.getenv("HUGGINGFACE_API_TOKEN", "")
    return await asyncio.to_thread(
        generate_image, prompt, api_token,
        int(os.getenv("IMAGE_WIDTH", 1024)),
        int(os.getenv("IMAGE_HEIGHT", 1024)),
    )


async def _upload_image(image_path: str, topic: str) -> str:
    """Run upload_to_s3 in a thread."""
    from upload_to_s3 import upload_to_s3
    bucket = os.getenv("R2_BUCKET", "n8nimages")
    return await asyncio.to_thread(upload_to_s3, image_path, bucket, None, True, topic)


async def _post_to_platform(platform: str, post_text: str, image_url: str, credentials: Dict) -> Dict:
    """Post to a single platform in a thread."""
    from post_to_platforms import post_to_linkedin, post_to_facebook, post_to_instagram
    posters = {
        "linkedin": post_to_linkedin,
        "facebook": post_to_facebook,
        "instagram": post_to_instagram,
    }
    poster = posters.get(platform)
    if not poster:
        return {"success": False, "platform": platform, "error": f"Unknown platform: {platform}"}
    return await asyncio.to_thread(poster, post_text, image_url, credentials.get(platform, {}))


# ── Background workers ────────────────────────────────────────────────────────

async def run_research_and_generate(sid: str, topic: str):
    session = sessions[sid]
    try:
        # Step 1 — Research trends
        session["workflow_status"] = "researching"
        push_event(sid, "status", {"workflow_status": "researching"})
        log(sid, "Researching current trends...")

        trends = await _research(topic)
        check_cancelled(sid)
        log(sid, "Trend research complete.")

        # Step 2 — Generate content
        session["workflow_status"] = "generating"
        push_event(sid, "status", {"workflow_status": "generating"})
        log(sid, "Generating platform-specific posts...")

        posts_data = await _generate_content(topic, trends)
        check_cancelled(sid)

        for platform in ["linkedin", "facebook", "instagram"]:
            session["posts"][platform]["content"] = posts_data.get(platform, "")
            session["posts"][platform]["hashtags"] = (
                posts_data.get("hashtags", {}).get(platform, [])
            )
            session["posts"][platform]["status"] = "pending"

        session["workflow_status"] = "reviewing_posts"
        push_event(sid, "posts_ready", {"posts": session["posts"]})
        push_event(sid, "status", {"workflow_status": "reviewing_posts"})
        log(sid, "Posts ready for review.")

    except asyncio.CancelledError:
        return  # stopped by user, already handled
    except BaseException as e:
        if is_cancelled(sid):
            return
        tb = traceback.format_exc()
        error_detail = f"{type(e).__name__}: {str(e) or '(no message)'}\n\n{tb}"
        session["workflow_status"] = "error"
        session["error"] = error_detail
        push_event(sid, "error", {"message": error_detail})


async def run_revise_post(sid: str, platform: str, feedback: str):
    session = sessions[sid]
    try:
        session["posts"][platform]["status"] = "revising"
        push_event(sid, "post_update", {
            "platform": platform, "status": "revising",
            "content": session["posts"][platform]["content"],
        })
        log(sid, f"Revising {platform} post...")

        # Build the posts dict in the format revise_posts expects
        current_posts = {
            p: session["posts"][p]["content"]
            for p in ["linkedin", "facebook", "instagram"]
        }
        current_posts["hashtags"] = {
            p: session["posts"][p]["hashtags"]
            for p in ["linkedin", "facebook", "instagram"]
        }

        revised = await _revise_content(current_posts, f"For {platform} only: {feedback}")

        session["posts"][platform]["content"] = revised.get(platform, session["posts"][platform]["content"])
        session["posts"][platform]["hashtags"] = (
            revised.get("hashtags", {}).get(platform, session["posts"][platform]["hashtags"])
        )
        session["posts"][platform]["status"] = "pending"
        push_event(sid, "post_update", {
            "platform": platform,
            "status": "pending",
            "content": session["posts"][platform]["content"],
            "hashtags": session["posts"][platform]["hashtags"],
        })
        log(sid, f"{platform.capitalize()} post revised.")

    except Exception as e:
        session["posts"][platform]["status"] = "pending"
        push_event(sid, "post_update", {
            "platform": platform, "status": "pending",
            "content": session["posts"][platform]["content"],
        })
        push_event(sid, "error", {"message": str(e)})


async def run_generate_image(sid: str, style: str = ""):
    session = sessions[sid]
    try:
        session["workflow_status"] = "generating_image"
        session["image"]["status"] = "generating"
        push_event(sid, "status", {"workflow_status": "generating_image"})
        push_event(sid, "image_update", {"status": "generating", "url": None})
        log(sid, "Generating image prompt...")

        # Build posts dict for prompt generation
        posts_dict = {
            p: session["posts"][p]["content"]
            for p in ["linkedin", "facebook", "instagram"]
        }
        posts_dict["hashtags"] = {
            p: session["posts"][p]["hashtags"]
            for p in ["linkedin", "facebook", "instagram"]
        }

        prompt = await _generate_image_prompt(posts_dict, style)
        check_cancelled(sid)
        log(sid, "Generating image with Flux AI (this may take ~15s)...")

        # Generate image
        image_data = await _generate_image(prompt)
        check_cancelled(sid)

        # Save image to .tmp
        image_path = Path(".tmp") / f"{sid}_post_image.png"
        image_path.parent.mkdir(exist_ok=True)
        image_path.write_bytes(image_data)

        log(sid, "Uploading image to Cloudflare R2...")
        image_url = await _upload_image(str(image_path), session["topic"])
        check_cancelled(sid)

        # Cache-bust so the browser always fetches the updated image
        image_url_display = f"{image_url}?t={int(datetime.now().timestamp())}"

        session["image"]["url"] = image_url_display
        session["image"]["status"] = "ready"
        session["workflow_status"] = "reviewing_image"
        push_event(sid, "image_update", {"status": "ready", "url": image_url_display})
        push_event(sid, "status", {"workflow_status": "reviewing_image"})
        log(sid, "Image ready for review.")

    except asyncio.CancelledError:
        return
    except BaseException as e:
        if is_cancelled(sid):
            return
        tb = traceback.format_exc()
        error_detail = f"{type(e).__name__}: {str(e) or '(no message)'}\n\n{tb}"
        session["image"]["status"] = "pending"
        session["workflow_status"] = "reviewing_posts"
        push_event(sid, "error", {"message": error_detail})
        push_event(sid, "status", {"workflow_status": "reviewing_posts"})


async def run_post_to_platforms(sid: str):
    session = sessions[sid]
    try:
        session["workflow_status"] = "posting"
        push_event(sid, "status", {"workflow_status": "posting"})
        log(sid, "Publishing posts to social media platforms...")

        # Load platform credentials
        from post_to_platforms import load_environment as load_platform_creds
        credentials = await asyncio.to_thread(load_platform_creds)

        image_url = (session["image"].get("url") or "").split("?")[0]  # strip cache-bust

        results = {}
        for platform in ["linkedin", "facebook", "instagram"]:
            check_cancelled(sid)
            post_text = session["posts"][platform]["content"]
            if not post_text:
                continue

            log(sid, f"Posting to {platform.capitalize()}...")
            try:
                result = await _post_to_platform(platform, post_text, image_url, credentials)
                results[platform] = result
                push_event(sid, "posting_result", {"platform": platform, "result": result})
                if result.get("success"):
                    log(sid, f"{platform.capitalize()} posted successfully!")
                else:
                    log(sid, f"{platform.capitalize()} failed: {result.get('error', 'unknown error')}")
            except Exception as e:
                results[platform] = {"success": False, "platform": platform, "error": str(e)}
                push_event(sid, "posting_result", {"platform": platform, "result": results[platform]})
                log(sid, f"{platform.capitalize()} failed: {e}")

        session["posting_results"] = results

        # Complete
        session["workflow_status"] = "complete"
        push_event(sid, "posting_complete", {"results": results})
        push_event(sid, "status", {"workflow_status": "complete"})
        push_event(sid, "complete", {})
        successful = sum(1 for r in results.values() if r.get("success"))
        log(sid, f"Publishing complete: {successful}/{len(results)} platforms succeeded.")

    except asyncio.CancelledError:
        return
    except BaseException as e:
        if is_cancelled(sid):
            return
        tb = traceback.format_exc()
        error_detail = f"{type(e).__name__}: {str(e) or '(no message)'}\n\n{tb}"
        session["workflow_status"] = "error"
        session["error"] = error_detail
        push_event(sid, "error", {"message": error_detail})


# ── Auth Routes ───────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TotpVerifyRequest(BaseModel):
    login_token: str
    totp_code: str


class ReconfigureTotpRequest(BaseModel):
    current_password: str


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    with open("static/login.html", encoding="utf-8") as f:
        return f.read()


@app.post("/auth/login")
async def auth_login(req: LoginRequest, request: Request):
    limited = check_rate_limit("login", request, req.username)
    if limited:
        return limited

    if req.username != AUTH_USERNAME:
        record_rate_limit_failure("login", request, req.username)
        return JSONResponse({"detail": "Invalid credentials"}, status_code=401)

    password_hash = current_password_hash()
    if not password_hash:
        return JSONResponse({"detail": "Password not configured on server"}, status_code=500)

    if not bcrypt.checkpw(req.password.encode(), password_hash.encode()):
        record_rate_limit_failure("login", request, req.username)
        return JSONResponse({"detail": "Invalid credentials"}, status_code=401)

    reset_rate_limit("login", request, req.username)
    login_token = auth_store.create_login_token(req.username)
    setup_required = not auth_store.has_totp_secret()
    return {
        "require_2fa": True,
        "login_token": login_token,
        "setup_required": setup_required,
        "message": (
            "Scan the QR code and save the setup key to finish securing your account."
            if setup_required
            else "2FA is already configured for this account. Enter the 6-digit code from your authenticator app."
        ),
    }


@app.get("/auth/setup-2fa-qr")
async def setup_2fa_qr(token: str):
    entry = auth_store.get_login_token(token)
    if not entry:
        return JSONResponse({"detail": "This setup link is invalid or expired. Please sign in again."}, status_code=401)

    has_existing_secret = auth_store.has_totp_secret()
    if has_existing_secret and not entry.get("allow_reconfigure"):
        return JSONResponse({"detail": "2FA is already configured for this account."}, status_code=400)

    pending_secret = auth_store.get_or_create_pending_totp_secret(token)
    if not pending_secret:
        return JSONResponse({"detail": "This setup link is invalid or expired. Please sign in again."}, status_code=401)

    totp = pyotp.TOTP(pending_secret)
    uri = totp.provisioning_uri(name=entry["username"], issuer_name=TOTP_ISSUER)

    img = qrcode.make(uri, image_factory=qrcode.image.pil.PilImage)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return StreamingResponse(buf, media_type="image/png",
                             headers={"Cache-Control": "no-store"})


@app.get("/auth/setup-2fa-secret")
async def setup_2fa_secret(token: str):
    entry = auth_store.get_login_token(token)
    if not entry:
        return JSONResponse({"detail": "This setup link is invalid or expired. Please sign in again."}, status_code=401)
    if auth_store.has_totp_secret() and not entry.get("allow_reconfigure"):
        return JSONResponse({"detail": "2FA is already configured for this account."}, status_code=400)

    pending_secret = auth_store.get_or_create_pending_totp_secret(token)
    if not pending_secret:
        return JSONResponse({"detail": "This setup link is invalid or expired. Please sign in again."}, status_code=401)

    return {
        "secret": pending_secret,
        "issuer": TOTP_ISSUER,
        "account_name": entry["username"],
        "message": "Save this setup key in a secure place in case you need to re-add the authenticator app later.",
    }


@app.post("/auth/verify-2fa")
async def auth_verify_2fa(req: TotpVerifyRequest, request: Request, response: Response):
    limited = check_rate_limit("totp", request, req.login_token)
    if limited:
        return limited

    entry = auth_store.get_login_token(req.login_token)
    if not entry:
        return JSONResponse({"detail": "Your sign-in step expired. Please enter your password again."}, status_code=401)

    stored_secret = current_totp_secret()
    use_pending_secret = bool(entry.get("pending_totp_secret")) and (entry.get("allow_reconfigure") or not stored_secret)
    secret = entry.get("pending_totp_secret") if use_pending_secret else stored_secret
    if not secret:
        return JSONResponse({"detail": "2FA is not ready yet. Restart the sign-in flow to continue."}, status_code=400)

    totp = pyotp.TOTP(secret)
    if not totp.verify(req.totp_code, valid_window=1):
        record_rate_limit_failure("totp", request, req.login_token)
        return JSONResponse({"detail": "Invalid 2FA code. Please try the latest code from your authenticator app."}, status_code=401)

    if entry.get("pending_totp_secret") and (entry.get("allow_reconfigure") or not stored_secret):
        save_totp_secret(entry["pending_totp_secret"])

    auth_store.delete_login_token(req.login_token)
    reset_rate_limit("totp", request, req.login_token)
    logger.info("Successful 2FA verification for %s", entry["username"])

    session_token = create_session_cookie(entry["username"])
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=cookie_should_be_secure(request),
        max_age=SESSION_MAX_AGE,
        path="/",
    )
    return {"authenticated": True}


@app.post("/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


# ── Password Reset & Change Routes ───────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@app.post("/auth/forgot-password")
async def forgot_password(req: ForgotPasswordRequest, request: Request):
    limited = check_rate_limit("forgot-password", request, req.email)
    if limited:
        return limited

    admin_email = current_admin_email()
    # Always return success to avoid leaking whether the email is valid
    if req.email.strip().lower() == admin_email.strip().lower() and admin_email:
        token = auth_store.create_reset_token()
        origin = f"{request.url.scheme}://{request.url.netloc}"
        reset_link = f"{origin}/reset-password?token={token}"
        body = f"""
        <h2>Password Reset Request</h2>
        <p>You requested a password reset for <b>Social Post Creator</b>.</p>
        <p>Click the link below to set a new password (expires in 15 minutes):</p>
        <p><a href="{reset_link}" style="display:inline-block;padding:12px 24px;background:#6366f1;color:#fff;border-radius:8px;text-decoration:none;font-weight:600">Reset Password</a></p>
        <p>If you didn't request this, ignore this email.</p>
        <p style="color:#888;font-size:12px">This link expires in 15 minutes.</p>
        """
        logger.info(f"Password reset requested for {req.email}")
        sent = send_email(admin_email, "Password Reset - Social Post Creator", body)
        if not sent:
            logger.warning("Failed to send reset email — check SMTP config")
    reset_rate_limit("forgot-password", request, req.email)
    return {"ok": True, "message": "If that email is registered, a reset link has been sent."}


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(token: str = ""):
    if not token or not auth_store.verify_reset_token(token):
        return HTMLResponse("<html><body><h2>Invalid or expired reset link.</h2><p><a href='/login'>Back to Login</a></p></body></html>")
    with open("static/reset-password.html", encoding="utf-8") as f:
        return f.read()


@app.post("/auth/reset-password")
async def reset_password(req: ResetPasswordRequest, request: Request):
    limited = check_rate_limit("reset-password", request, req.token)
    if limited:
        return limited

    if not auth_store.consume_reset_token(req.token):
        record_rate_limit_failure("reset-password", request, req.token)
        return JSONResponse({"detail": "Invalid or expired reset token"}, status_code=400)

    if len(req.new_password) < 8:
        return JSONResponse({"detail": "Password must be at least 8 characters"}, status_code=400)

    new_hash = bcrypt.hashpw(req.new_password.encode(), bcrypt.gensalt()).decode()
    update_password_hash(new_hash)
    reset_rate_limit("reset-password", request, req.token)

    admin_email = current_admin_email()
    if admin_email:
        send_email(admin_email, "Password Changed - Social Post Creator",
                   "<p>Your password for <b>Social Post Creator</b> was reset successfully via the reset link.</p>")

    return {"ok": True, "message": "Password reset successfully. You can now log in."}


@app.post("/auth/change-password")
async def change_password(req: ChangePasswordRequest, request: Request):
    password_hash = current_password_hash()
    if not password_hash:
        return JSONResponse({"detail": "Password not configured"}, status_code=500)

    if not bcrypt.checkpw(req.current_password.encode(), password_hash.encode()):
        return JSONResponse({"detail": "Current password is incorrect"}, status_code=401)

    if len(req.new_password) < 8:
        return JSONResponse({"detail": "New password must be at least 8 characters"}, status_code=400)

    new_hash = bcrypt.hashpw(req.new_password.encode(), bcrypt.gensalt()).decode()
    update_password_hash(new_hash)

    admin_email = current_admin_email()
    if admin_email:
        send_email(admin_email, "Password Changed - Social Post Creator",
                   "<p>Your password for <b>Social Post Creator</b> was changed successfully.</p>")

    return {"ok": True, "message": "Password changed successfully."}


@app.post("/auth/reconfigure-2fa")
async def reconfigure_2fa(req: ReconfigureTotpRequest, request: Request):
    password_hash = current_password_hash()
    if not password_hash:
        return JSONResponse({"detail": "Password not configured"}, status_code=500)
    if not bcrypt.checkpw(req.current_password.encode(), password_hash.encode()):
        return JSONResponse({"detail": "Current password is incorrect"}, status_code=401)

    login_token = auth_store.create_login_token(request.state.user, allow_reconfigure=True)
    logger.info("2FA reconfiguration initiated for %s", request.state.user)
    return {
        "ok": True,
        "login_token": login_token,
        "message": "Scan the new QR code and verify a code to finish reconfiguring 2FA.",
    }


# ── API Routes ────────────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    topic: str

class ReviseRequest(BaseModel):
    feedback: str


@app.post("/api/start")
async def start_workflow(req: StartRequest, background_tasks: BackgroundTasks):
    sid = new_session(req.topic)
    background_tasks.add_task(run_research_and_generate, sid, req.topic)
    return {"session_id": sid}


@app.get("/api/session/{sid}")
async def get_session(sid: str):
    if sid not in sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return sessions[sid]


@app.get("/api/debug/{sid}")
async def debug_session(sid: str):
    """Return session state with full error detail, formatted for easy reading."""
    if not ENABLE_DEBUG_API:
        return JSONResponse({"detail": "Debug API is disabled in this environment."}, status_code=404)
    if sid not in sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    s = sessions[sid]
    return JSONResponse({
        "workflow_status": s["workflow_status"],
        "log": s["log"],
        "error": s["error"],
        "image_status": s["image"]["status"],
        "posts_status": {p: s["posts"][p]["status"] for p in s["posts"]},
    })


@app.get("/api/sessions")
async def list_sessions():
    """List all active sessions with their status."""
    return [
        {"id": sid, "topic": s["topic"], "workflow_status": s["workflow_status"], "error": bool(s["error"])}
        for sid, s in sessions.items()
    ]


@app.get("/api/events/{sid}")
async def event_stream(sid: str, request: Request):
    if sid not in event_queues:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    async def generator():
        q = event_queues[sid]
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(q.get(), timeout=20)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "complete":
                    break
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/stop/{sid}")
async def stop_workflow(sid: str):
    if sid not in sessions:
        return JSONResponse({"error": "Not found"}, status_code=404)
    session = sessions[sid]
    session["cancelled"] = True
    session["workflow_status"] = "stopped"
    push_event(sid, "status", {"workflow_status": "stopped"})
    push_event(sid, "stopped", {})
    log(sid, "Workflow stopped by user.")
    return {"ok": True}


@app.post("/api/posts/{sid}/approve/{platform}")
async def approve_post(sid: str, platform: str, background_tasks: BackgroundTasks):
    if sid not in sessions:
        return JSONResponse({"error": "Not found"}, status_code=404)
    session = sessions[sid]
    session["posts"][platform]["status"] = "approved"
    push_event(sid, "post_update", {"platform": platform, "status": "approved"})
    log(sid, f"{platform.capitalize()} post approved.")

    # Trigger image generation once ALL posts are approved
    all_approved = all(p["status"] == "approved" for p in session["posts"].values())
    if all_approved and session["workflow_status"] == "reviewing_posts":
        background_tasks.add_task(run_generate_image, sid)

    return {"ok": True}


@app.post("/api/posts/{sid}/revise/{platform}")
async def revise_post(sid: str, platform: str, req: ReviseRequest, background_tasks: BackgroundTasks):
    if sid not in sessions:
        return JSONResponse({"error": "Not found"}, status_code=404)
    background_tasks.add_task(run_revise_post, sid, platform, req.feedback)
    return {"ok": True}


@app.post("/api/image/{sid}/approve")
async def approve_image(sid: str, background_tasks: BackgroundTasks):
    if sid not in sessions:
        return JSONResponse({"error": "Not found"}, status_code=404)
    session = sessions[sid]
    session["image"]["status"] = "approved"
    push_event(sid, "image_update", {"status": "approved", "url": session["image"]["url"]})
    log(sid, "Image approved. Starting platform publishing...")
    background_tasks.add_task(run_post_to_platforms, sid)
    return {"ok": True}


@app.post("/api/image/{sid}/revise")
async def revise_image(sid: str, req: ReviseRequest, background_tasks: BackgroundTasks):
    if sid not in sessions:
        return JSONResponse({"error": "Not found"}, status_code=404)
    background_tasks.add_task(run_generate_image, sid, req.feedback)
    return {"ok": True}


# ── Static files & entry point ────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
