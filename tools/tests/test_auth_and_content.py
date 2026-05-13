#!/usr/bin/env python3
"""
Regression tests for durable auth state and content cleanup.
"""

import importlib
import os
import sys
import types
from pathlib import Path

import bcrypt
import pyotp
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.generate_content import clean_post_text, normalize_posts


def load_app_module(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    password_hash = bcrypt.hashpw(b"secret-pass", bcrypt.gensalt()).decode()

    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("AUTH_USERNAME", "admin")
    monkeypatch.setenv("AUTH_PASSWORD_HASH", password_hash)
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("AUTH_DB_PATH", str(db_path))
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ENABLE_DEBUG_API", "false")
    monkeypatch.delenv("TOTP_SECRET", raising=False)

    class FakeQrImage:
        def save(self, buf, format="PNG"):
            buf.write(b"fake-png")

    fake_qrcode = types.ModuleType("qrcode")
    fake_qrcode.make = lambda *args, **kwargs: FakeQrImage()
    fake_qrcode_image = types.ModuleType("qrcode.image")
    fake_qrcode_image_pil = types.ModuleType("qrcode.image.pil")
    fake_qrcode_image_pil.PilImage = object
    fake_qrcode.image = fake_qrcode_image
    sys.modules["qrcode"] = fake_qrcode
    sys.modules["qrcode.image"] = fake_qrcode_image
    sys.modules["qrcode.image.pil"] = fake_qrcode_image_pil

    if "app" in sys.modules:
        del sys.modules["app"]
    module = importlib.import_module("app")
    return importlib.reload(module)


def test_first_time_2fa_persists_across_reload(tmp_path, monkeypatch):
    app_module = load_app_module(tmp_path, monkeypatch)
    client = TestClient(app_module.app)

    login = client.post("/auth/login", json={"username": "admin", "password": "secret-pass"})
    assert login.status_code == 200
    payload = login.json()
    assert payload["setup_required"] is True

    token = payload["login_token"]
    secret_res = client.get(f"/auth/setup-2fa-secret?token={token}")
    assert secret_res.status_code == 200
    secret = secret_res.json()["secret"]

    verify = client.post(
        "/auth/verify-2fa",
        json={"login_token": token, "totp_code": pyotp.TOTP(secret).now()},
    )
    assert verify.status_code == 200

    reloaded_module = load_app_module(tmp_path, monkeypatch)
    reloaded_client = TestClient(reloaded_module.app)
    relogin = reloaded_client.post("/auth/login", json={"username": "admin", "password": "secret-pass"})
    assert relogin.status_code == 200
    assert relogin.json()["setup_required"] is False


def test_password_reset_survives_reload(tmp_path, monkeypatch):
    app_module = load_app_module(tmp_path, monkeypatch)
    client = TestClient(app_module.app)

    token = app_module.auth_store.create_reset_token()
    reset = client.post("/auth/reset-password", json={"token": token, "new_password": "new-secret-pass"})
    assert reset.status_code == 200

    reloaded_module = load_app_module(tmp_path, monkeypatch)
    reloaded_client = TestClient(reloaded_module.app)
    login = reloaded_client.post("/auth/login", json={"username": "admin", "password": "new-secret-pass"})
    assert login.status_code == 200


def test_debug_endpoint_disabled_by_default(tmp_path, monkeypatch):
    app_module = load_app_module(tmp_path, monkeypatch)
    client = TestClient(app_module.app)

    login = client.post("/auth/login", json={"username": "admin", "password": "secret-pass"})
    token = login.json()["login_token"]
    secret = client.get(f"/auth/setup-2fa-secret?token={token}").json()["secret"]
    client.post("/auth/verify-2fa", json={"login_token": token, "totp_code": pyotp.TOTP(secret).now()})

    response = client.get("/api/debug/unknown-session")
    assert response.status_code == 404
    assert response.json()["detail"] == "Debug API is disabled in this environment."


def test_clean_post_text_removes_markdown_artifacts():
    dirty = "**Bold intro**\n\n- Creative idea with `formatting` and __extra__ markers."
    cleaned = clean_post_text(dirty)
    assert "**" not in cleaned
    assert "__" not in cleaned
    assert "`" not in cleaned
    assert cleaned.startswith("Bold intro")


def test_normalize_posts_moves_hashtags_out_of_body_text():
    raw_posts = {
        "linkedin": "**Bold intro**\n\nA clean paragraph about hiring trends. #Hiring #Careers",
        "facebook": "Plain body copy\n#Community #Careers",
        "instagram": "Visual hook with #Growth",
        "hashtags": {
            "linkedin": ["#Leadership"],
            "facebook": [],
            "instagram": ["#Growth", "#Brand"]
        }
    }

    normalized = normalize_posts(raw_posts)

    assert normalized["linkedin"] == "Bold intro\n\nA clean paragraph about hiring trends."
    assert normalized["facebook"] == "Plain body copy"
    assert normalized["instagram"] == "Visual hook with"
    assert normalized["hashtags"]["linkedin"] == ["#Leadership", "#Hiring", "#Careers"]
    assert normalized["hashtags"]["facebook"] == ["#Community", "#Careers"]
    assert normalized["hashtags"]["instagram"] == ["#Growth", "#Brand"]


def test_normalize_posts_keeps_body_plain_text_without_hash_symbols():
    raw_posts = {
        "linkedin": "Paragraph one.\n\nParagraph two with #Topic and **formatting**.",
        "facebook": "",
        "instagram": "",
        "hashtags": {
            "linkedin": [],
            "facebook": [],
            "instagram": []
        }
    }

    normalized = normalize_posts(raw_posts)

    assert "#" not in normalized["linkedin"]
    assert "**" not in normalized["linkedin"]
    assert normalized["hashtags"]["linkedin"] == ["#Topic"]
