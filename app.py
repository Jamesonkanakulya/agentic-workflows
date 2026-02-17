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
import os
import secrets
import sys
import time
import traceback
import uuid
from datetime import datetime
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
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD_HASH = os.getenv("AUTH_PASSWORD_HASH", "")
TOTP_SECRET = os.getenv("TOTP_SECRET", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")

if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET must be set in .env")

serializer = URLSafeTimedSerializer(SESSION_SECRET)
SESSION_COOKIE = "session_token"
SESSION_MAX_AGE = 86400  # 24 hours
TOTP_ISSUER = "SocialPostCreator"

# Temporary tokens between password step and 2FA step
pending_2fa: Dict[str, Dict] = {}


def create_session_cookie(username: str) -> str:
    return serializer.dumps({"user": username, "nonce": secrets.token_hex(8)})


def verify_session_cookie(token: str) -> dict | None:
    try:
        return serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def create_login_token(username: str) -> str:
    token = secrets.token_urlsafe(32)
    pending_2fa[token] = {"username": username, "created": time.time()}
    return token


def consume_login_token(token: str) -> dict | None:
    entry = pending_2fa.pop(token, None)
    if not entry or time.time() - entry["created"] > 300:
        return None
    return entry


def verify_login_token(token: str) -> dict | None:
    entry = pending_2fa.get(token)
    if not entry or time.time() - entry["created"] > 300:
        return None
    return entry


# ── App setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="Social Post Creator")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

AUTH_EXEMPT = {"/login", "/auth/login", "/auth/verify-2fa", "/auth/setup-2fa-qr", "/auth/logout"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in AUTH_EXEMPT or path.startswith("/static/"):
        return await call_next(request)
    token = request.cookies.get(SESSION_COOKIE)
    if not token or not verify_session_cookie(token):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return RedirectResponse(url="/login", status_code=302)
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


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    with open("static/login.html", encoding="utf-8") as f:
        return f.read()


@app.post("/auth/login")
async def auth_login(req: LoginRequest):
    if req.username != AUTH_USERNAME:
        return JSONResponse({"detail": "Invalid credentials"}, status_code=401)

    if not AUTH_PASSWORD_HASH:
        return JSONResponse({"detail": "Password not configured on server"}, status_code=500)

    if not bcrypt.checkpw(req.password.encode(), AUTH_PASSWORD_HASH.encode()):
        return JSONResponse({"detail": "Invalid credentials"}, status_code=401)

    login_token = create_login_token(req.username)
    return {
        "require_2fa": True,
        "login_token": login_token,
        "setup_required": not bool(TOTP_SECRET),
    }


@app.get("/auth/setup-2fa-qr")
async def setup_2fa_qr(token: str):
    entry = verify_login_token(token)
    if not entry:
        return JSONResponse({"detail": "Invalid or expired token"}, status_code=401)

    if TOTP_SECRET:
        return JSONResponse({"detail": "2FA already configured"}, status_code=400)

    new_secret = pyotp.random_base32()
    entry["pending_totp_secret"] = new_secret

    totp = pyotp.TOTP(new_secret)
    uri = totp.provisioning_uri(name=entry["username"], issuer_name=TOTP_ISSUER)

    img = qrcode.make(uri, image_factory=qrcode.image.pil.PilImage)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return StreamingResponse(buf, media_type="image/png",
                             headers={"Cache-Control": "no-store"})


@app.post("/auth/verify-2fa")
async def auth_verify_2fa(req: TotpVerifyRequest, response: Response):
    entry = pending_2fa.get(req.login_token)
    if not entry or time.time() - entry["created"] > 300:
        pending_2fa.pop(req.login_token, None)
        return JSONResponse({"detail": "Invalid or expired login token"}, status_code=401)

    secret = TOTP_SECRET or entry.get("pending_totp_secret")
    if not secret:
        return JSONResponse({"detail": "No TOTP secret configured"}, status_code=400)

    totp = pyotp.TOTP(secret)
    if not totp.verify(req.totp_code, valid_window=1):
        return JSONResponse({"detail": "Invalid TOTP code"}, status_code=401)

    # First-time setup: print secret to console
    if not TOTP_SECRET and entry.get("pending_totp_secret"):
        print(f"\n{'='*60}")
        print(f"  2FA SETUP COMPLETE")
        print(f"  Add this to your .env file:")
        print(f"  TOTP_SECRET={entry['pending_totp_secret']}")
        print(f"{'='*60}\n")

    pending_2fa.pop(req.login_token, None)

    session_token = create_session_cookie(entry["username"])
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=SESSION_MAX_AGE,
        path="/",
    )
    return {"authenticated": True}


@app.post("/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


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
