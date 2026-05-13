#!/usr/bin/env python3
"""
Tests for app auth persistence helpers.

Run with: pytest tools/tests/test_auth_persistence.py -v
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parents[2]))

import app


def test_auth_store_persists_totp_secret(tmp_path):
    db_path = tmp_path / "auth.db"
    store = app.AuthStore(db_path)

    store.set_totp_secret("JBSWY3DPEHPK3PXP")

    reloaded_store = app.AuthStore(db_path)
    assert reloaded_store.get_totp_secret() == "JBSWY3DPEHPK3PXP"
    assert reloaded_store.has_totp_secret() is True


def test_auth_store_reuses_pending_totp_secret(tmp_path):
    store = app.AuthStore(tmp_path / "auth.db")
    token = store.create_login_token("admin")

    first_secret = store.get_or_create_pending_totp_secret(token)
    second_secret = store.get_or_create_pending_totp_secret(token)

    assert first_secret
    assert second_secret == first_secret

