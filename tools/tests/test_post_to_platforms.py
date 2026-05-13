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
from post_to_platforms import (
    _resolve_linkedin_author_urn,
    _linkedin_share_payload,
    load_environment,
    post_to_linkedin,
)


class FakeResponse:
    """Minimal requests response for LinkedIn posting tests."""

    def __init__(self, status_code, data=None, text="", headers=None, content=b""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text
        self.headers = headers or {}
        self.content = content

    def json(self):
        return self._data


class TestLinkedInEnvironment:
    """Test LinkedIn environment loading."""

    def test_prefers_author_urn_over_legacy_person_urn(self, monkeypatch):
        monkeypatch.setattr(post_to_platforms, 'load_dotenv', lambda override=True: None)
        monkeypatch.setenv('LINKEDIN_ACCESS_TOKEN', 'test-token')
        monkeypatch.setenv('LINKEDIN_AUTHOR_URN', 'urn:li:person:new_id')
        monkeypatch.setenv('LINKEDIN_PERSON_URN', 'urn:li:person:old_id')
        monkeypatch.setenv('LINKEDIN_VERSION', '202601')

        credentials = load_environment()

        assert credentials['linkedin']['author_urn'] == 'urn:li:person:new_id'
        assert credentials['linkedin']['person_urn'] == 'urn:li:person:old_id'
        assert credentials['linkedin']['linkedin_version'] == '202601'

    def test_falls_back_to_legacy_person_urn(self, monkeypatch):
        monkeypatch.setattr(post_to_platforms, 'load_dotenv', lambda override=True: None)
        monkeypatch.delenv('LINKEDIN_AUTHOR_URN', raising=False)
        monkeypatch.setenv('LINKEDIN_PERSON_URN', 'urn:li:person:mb5LMCFt_K')

        credentials = load_environment()

        assert credentials['linkedin']['author_urn'] == 'urn:li:person:mb5LMCFt_K'


class TestLinkedInAuthorUrnValidation:
    """Test LinkedIn REST Posts API author URN validation."""

    def test_accepts_person_urn(self):
        assert (
            _resolve_linkedin_author_urn({'author_urn': 'urn:li:person:mb5LMCFt_K'})
            == 'urn:li:person:mb5LMCFt_K'
        )

    def test_accepts_organization_urn(self):
        assert (
            _resolve_linkedin_author_urn({'author_urn': 'urn:li:organization:123456'})
            == 'urn:li:organization:123456'
        )

    def test_rejects_missing_urn(self):
        with pytest.raises(ValueError, match="LinkedIn author URN not configured"):
            _resolve_linkedin_author_urn({})

    def test_rejects_member_urn(self):
        with pytest.raises(ValueError, match="old UGC API path"):
            _resolve_linkedin_author_urn({'author_urn': 'urn:li:member:123456'})

    def test_rejects_malformed_urn(self):
        with pytest.raises(ValueError, match="urn:li:person:<id>"):
            _resolve_linkedin_author_urn({'author_urn': 'urn:li:organization:abc123'})

    def test_supports_legacy_key_when_value_is_valid(self):
        assert (
            _resolve_linkedin_author_urn({'person_urn': 'urn:li:person:mb5LMCFt_K'})
            == 'urn:li:person:mb5LMCFt_K'
        )


class TestLinkedInPosting:
    """Test LinkedIn REST Posts API payloads."""

    def test_text_only_post_uses_rest_posts_payload(self, monkeypatch):
        captured = {}

        def fake_post(url, headers, json, timeout):
            captured['url'] = url
            captured['headers'] = headers
            captured['json'] = json
            return FakeResponse(201, headers={'x-restli-id': 'urn:li:share:111'})

        monkeypatch.setattr(post_to_platforms.requests, 'post', fake_post)

        result = post_to_linkedin(
            'Test LinkedIn post',
            None,
            {
                'access_token': 'test-token',
                'author_urn': 'urn:li:person:mb5LMCFt_K',
                'linkedin_version': '202601',
            },
        )

        assert result['success'] is True
        assert result['post_id'] == 'urn:li:share:111'
        assert captured['url'] == 'https://api.linkedin.com/rest/posts'
        assert captured['headers']['Linkedin-Version'] == '202601'
        assert captured['json'] == {
            'author': 'urn:li:person:mb5LMCFt_K',
            'commentary': 'Test LinkedIn post',
            'visibility': 'PUBLIC',
            'distribution': {
                'feedDistribution': 'MAIN_FEED',
                'targetEntities': [],
                'thirdPartyDistributionChannels': []
            },
            'lifecycleState': 'PUBLISHED',
            'isReshareDisabledByAuthor': False
        }

    def test_image_post_initializes_upload_then_posts_image_content(self, monkeypatch):
        calls = []

        def fake_post(url, headers, json, timeout):
            calls.append(('post', url, json))
            if url == 'https://api.linkedin.com/rest/images?action=initializeUpload':
                return FakeResponse(
                    200,
                    {
                        'value': {
                            'uploadUrl': 'https://uploads.linkedin.test/image',
                            'image': 'urn:li:image:abc123'
                        }
                    }
                )
            return FakeResponse(201, headers={'x-restli-id': 'urn:li:share:222'})

        def fake_get(url, timeout):
            calls.append(('get', url, None))
            return FakeResponse(200, content=b'image-bytes')

        def fake_put(url, headers, data, timeout):
            calls.append(('put', url, data))
            return FakeResponse(201)

        monkeypatch.setattr(post_to_platforms.requests, 'post', fake_post)
        monkeypatch.setattr(post_to_platforms.requests, 'get', fake_get)
        monkeypatch.setattr(post_to_platforms.requests, 'put', fake_put)

        result = post_to_linkedin(
            'Post with image',
            'https://cdn.example.test/post.png',
            {
                'access_token': 'test-token',
                'author_urn': 'urn:li:person:mb5LMCFt_K',
                'linkedin_version': '202601',
            },
        )

        assert result['success'] is True
        assert calls[0] == (
            'post',
            'https://api.linkedin.com/rest/images?action=initializeUpload',
            {'initializeUploadRequest': {'owner': 'urn:li:person:mb5LMCFt_K'}}
        )
        assert calls[1] == ('get', 'https://cdn.example.test/post.png', None)
        assert calls[2] == ('put', 'https://uploads.linkedin.test/image', b'image-bytes')
        assert calls[3][0] == 'post'
        assert calls[3][1] == 'https://api.linkedin.com/rest/posts'
        assert calls[3][2]['content'] == {
            'media': {
                'id': 'urn:li:image:abc123'
            }
        }

    def test_rest_posts_403_falls_back_to_shares_api(self, monkeypatch):
        calls = []

        def fake_post(url, headers, json, timeout):
            calls.append((url, json))
            if url == 'https://api.linkedin.com/rest/posts':
                return FakeResponse(403, text='{"message":"","status":403}')
            return FakeResponse(201, {'activity': 'urn:li:activity:333'})

        monkeypatch.setattr(post_to_platforms.requests, 'post', fake_post)

        result = post_to_linkedin(
            'Fallback post',
            None,
            {
                'access_token': 'test-token',
                'author_urn': 'urn:li:person:mb5LMCFt_K',
                'linkedin_version': '202601',
            },
        )

        assert result['success'] is True
        assert result['post_id'] == 'urn:li:activity:333'
        assert calls[0][0] == 'https://api.linkedin.com/rest/posts'
        assert calls[1] == (
            'https://api.linkedin.com/v2/shares',
            {
                'owner': 'urn:li:person:mb5LMCFt_K',
                'text': {
                    'text': 'Fallback post'
                },
                'subject': 'Fallback post',
                'distribution': {
                    'linkedInDistributionTarget': {}
                }
            }
        )

    def test_share_payload_includes_image_link_card(self):
        payload = _linkedin_share_payload(
            'Share with image',
            'urn:li:person:mb5LMCFt_K',
            'https://cdn.example.test/post.png',
        )

        assert payload['owner'] == 'urn:li:person:mb5LMCFt_K'
        assert payload['content'] == {
            'contentEntities': [
                {
                    'entityLocation': 'https://cdn.example.test/post.png',
                    'thumbnails': [
                        {
                            'resolvedUrl': 'https://cdn.example.test/post.png'
                        }
                    ]
                }
            ],
            'title': 'Share with image'
        }
