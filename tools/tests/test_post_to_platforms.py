#!/usr/bin/env python3
"""
Tests for post_to_platforms.py

Run with: pytest tools/tests/test_post_to_platforms.py -v
"""

import sys
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import post_to_platforms
from post_to_platforms import _resolve_linkedin_author_urn, post_to_linkedin


class FakeResponse:
    """Minimal requests response for LinkedIn posting tests."""

    def __init__(self, status_code, data=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


class TestLinkedInAuthorUrnValidation:
    """Test LinkedIn author URN validation."""

    def test_accepts_member_urn(self):
        assert (
            _resolve_linkedin_author_urn({'member_urn': 'urn:li:member:123456'})
            == 'urn:li:member:123456'
        )

    def test_accepts_company_urn(self):
        assert (
            _resolve_linkedin_author_urn({'member_urn': 'urn:li:company:987654'})
            == 'urn:li:company:987654'
        )

    def test_rejects_missing_urn(self):
        with pytest.raises(ValueError, match="LinkedIn member URN not configured"):
            _resolve_linkedin_author_urn({})

    def test_rejects_person_urn(self):
        with pytest.raises(ValueError, match="Use LINKEDIN_MEMBER_URN=urn:li:member:<numeric_id>"):
            _resolve_linkedin_author_urn({'member_urn': 'urn:li:person:mb5LMCFt_K'})

    def test_rejects_malformed_urn(self):
        with pytest.raises(ValueError, match="urn:li:member:<digits>"):
            _resolve_linkedin_author_urn({'member_urn': 'urn:li:member:abc123'})

    def test_supports_legacy_key_when_value_is_valid(self):
        assert (
            _resolve_linkedin_author_urn({'person_urn': 'urn:li:member:123456'})
            == 'urn:li:member:123456'
        )

    def test_member_urn_takes_precedence_over_legacy_key(self):
        assert (
            _resolve_linkedin_author_urn({
                'member_urn': 'urn:li:member:123456',
                'person_urn': 'urn:li:person:mb5LMCFt_K',
            })
            == 'urn:li:member:123456'
        )


class TestLinkedInPosting:
    """Test LinkedIn post payloads."""

    def test_post_payload_uses_member_urn_author(self, monkeypatch):
        captured = {}

        def fake_post(url, headers, json, timeout):
            captured['url'] = url
            captured['json'] = json
            return FakeResponse(201, {'id': 'urn:li:share:111'})

        monkeypatch.setattr(post_to_platforms.requests, 'post', fake_post)

        result = post_to_linkedin(
            'Test LinkedIn post',
            None,
            {
                'access_token': 'test-token',
                'member_urn': 'urn:li:member:123456',
            },
        )

        assert result['success'] is True
        assert captured['url'] == 'https://api.linkedin.com/v2/ugcPosts'
        assert captured['json']['author'] == 'urn:li:member:123456'

