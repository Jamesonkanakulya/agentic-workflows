#!/usr/bin/env python3
"""
Diagnostic script — run this while the server is running (or standalone)
to pinpoint exactly which step is failing and why.

Usage:
    python diagnose.py
    python diagnose.py --topic "Your Topic Here"
    python diagnose.py --session <session_id>   # inspect a live session
"""

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "tools"))
from dotenv import load_dotenv
load_dotenv()

SERVER = "http://localhost:8000"


# ── Helpers ──────────────────────────────────────────────────────────────────

def ok(msg): print(f"  [OK]  {msg}")
def fail(msg): print(f"  [FAIL] {msg}")
def info(msg): print(f"  [--]  {msg}")
def section(title): print(f"\n{'='*60}\n  {title}\n{'='*60}")


# ── 1. Environment variables ──────────────────────────────────────────────────

def check_env():
    section("1. Environment Variables")
    required = {
        "TAVILY_API_KEY": "Trend research (Tavily)",
        "GITHUB_TOKEN": "Content generation (GPT-4o / GitHub Models)",
        "HUGGINGFACE_API_TOKEN": "Image generation (Flux AI)",
    }
    optional = {
        "R2_BUCKET": "Cloudflare R2 bucket name",
        "GITHUB_ENDPOINT": "GitHub Models endpoint (has default)",
        "GITHUB_MODEL": "GitHub model name (has default)",
        "IMAGE_WIDTH": "Image width (default 1024)",
        "IMAGE_HEIGHT": "Image height (default 1024)",
    }
    all_ok = True
    for key, desc in required.items():
        v = os.getenv(key)
        if v:
            ok(f"{key}: SET ({len(v)} chars)  — {desc}")
        else:
            fail(f"{key}: MISSING  — {desc}")
            all_ok = False
    for key, desc in optional.items():
        v = os.getenv(key)
        status = f"SET ({len(v)} chars)" if v else "not set (using default)"
        info(f"{key}: {status}  — {desc}")
    return all_ok


# ── 2. Server check ───────────────────────────────────────────────────────────

def check_server():
    section("2. Server Connectivity")
    try:
        with urllib.request.urlopen(f"{SERVER}/api/sessions", timeout=3) as r:
            data = json.loads(r.read())
            ok(f"Server responding — {len(data)} active session(s)")
            for s in data:
                status = "ERROR" if s["error"] else s["workflow_status"]
                info(f"  Session {s['id'][:8]}... topic={s['topic']!r} status={status}")
            return True
    except Exception as e:
        fail(f"Server not reachable: {e}")
        info("Start it with: python app.py")
        return False


# ── 3. Inspect a specific session ─────────────────────────────────────────────

def inspect_session(sid: str):
    section(f"3. Session Debug: {sid[:8]}...")
    try:
        with urllib.request.urlopen(f"{SERVER}/api/debug/{sid}", timeout=3) as r:
            data = json.loads(r.read())
        print(f"  workflow_status : {data['workflow_status']}")
        print(f"  posts_status    : {data['posts_status']}")
        print(f"  image_status    : {data['image_status']}")
        print(f"  log             : {data['log']}")
        if data["error"]:
            fail("Error detail:")
            print(data["error"])
        else:
            ok("No errors")
    except Exception as e:
        fail(f"Could not fetch session: {e}")


# ── 4. Tool tests ─────────────────────────────────────────────────────────────

def test_research(topic: str):
    section("4. Research Tool (Tavily)")
    try:
        from research_trends import research_trends
        info(f"Testing with topic: {topic!r}")
        t0 = time.time()
        result = research_trends(topic, 3)
        elapsed = time.time() - t0
        ok(f"research_trends OK in {elapsed:.1f}s — {result['total_results']} insights")
        return result
    except SystemExit as e:
        fail(f"SystemExit({e.code}) — likely missing TAVILY_API_KEY")
        traceback.print_exc()
        return None
    except Exception as e:
        fail(f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return None


def test_generate_content(topic: str, trends: dict):
    section("5. Content Generation Tool (GPT-4o)")
    try:
        from generate_content import generate_posts
        trends_context = (
            f"Topic: {trends.get('topic', topic)}\n\n"
            f"Summary: {trends.get('summary', '')}\n\nKey Insights:\n"
        )
        for i, ins in enumerate(trends.get("insights", [])[:3], 1):
            trends_context += f"\n{i}. {ins.get('title', '')}\n{ins.get('content', '')[:300]}\n"
        info("Calling generate_posts...")
        t0 = time.time()
        result = generate_posts(topic, trends_context)
        elapsed = time.time() - t0
        ok(f"generate_posts OK in {elapsed:.1f}s — keys: {list(result.keys())}")
        return result
    except SystemExit as e:
        fail(f"SystemExit({e.code}) — likely missing GITHUB_TOKEN or model error")
        traceback.print_exc()
        return None
    except Exception as e:
        fail(f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return None


def test_image_prompt(posts: dict):
    section("6. Image Prompt Generation")
    try:
        from generate_image_prompt import generate_image_prompt
        t0 = time.time()
        prompt = generate_image_prompt(posts, "modern professional")
        elapsed = time.time() - t0
        ok(f"generate_image_prompt OK in {elapsed:.1f}s — {len(prompt)} chars")
        info(f"Prompt preview: {prompt[:100]}...")
        return prompt
    except Exception as e:
        fail(f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return None


def test_image_generation(prompt: str):
    section("7. Image Generation (Flux AI / HuggingFace)")
    try:
        from generate_image import generate_image
        api_token = os.getenv("HUGGINGFACE_API_TOKEN", "")
        width = int(os.getenv("IMAGE_WIDTH", 512))   # smaller for faster test
        height = int(os.getenv("IMAGE_HEIGHT", 512))
        info(f"Generating {width}x{height} image...")
        t0 = time.time()
        img_bytes = generate_image(prompt, api_token, width, height)
        elapsed = time.time() - t0
        ok(f"generate_image OK in {elapsed:.1f}s — {len(img_bytes):,} bytes")
        return img_bytes
    except Exception as e:
        fail(f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Diagnose the Social Post Creator workflow")
    parser.add_argument("--topic", default="AI automation for small business", help="Topic to test with")
    parser.add_argument("--session", help="Inspect a specific running session by ID")
    parser.add_argument("--skip-image", action="store_true", help="Skip image generation test (saves ~15s)")
    args = parser.parse_args()

    print("\n Social Post Creator — Diagnostic Tool")

    # Always check env and server
    env_ok = check_env()
    server_ok = check_server()

    # If a session ID was given, inspect it and stop
    if args.session:
        inspect_session(args.session)
        return

    if not env_ok:
        print("\n[!] Fix missing env vars first, then re-run.")
        return

    # Run each tool in sequence, stopping on first failure
    section(f"Testing full pipeline with topic: {args.topic!r}")

    trends = test_research(args.topic)
    if not trends:
        print("\n[!] Research failed — check TAVILY_API_KEY and network")
        return

    posts = test_generate_content(args.topic, trends)
    if not posts:
        print("\n[!] Content generation failed — check GITHUB_TOKEN")
        return

    prompt = test_image_prompt(posts)
    if not prompt:
        print("\n[!] Image prompt generation failed")
        return

    if not args.skip_image:
        img = test_image_generation(prompt)
        if not img:
            print("\n[!] Image generation failed — check HUGGINGFACE_API_TOKEN")
    else:
        info("Image generation skipped (--skip-image)")

    section("Summary")
    print("  All tested steps passed! The web UI should work.")
    print("  If the web UI still fails, check: python diagnose.py --session <id>")
    print("  while the server is running and a session has been started.\n")


if __name__ == "__main__":
    main()
