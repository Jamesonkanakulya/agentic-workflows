#!/usr/bin/env python3
"""
Tests for generate_content.py

Run with: pytest tools/tests/test_generate_content.py -v
"""

import json
import os
import sys
from pathlib import Path
import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from generate_content import generate_posts, save_posts, CHAR_LIMITS


class TestGenerateContent:
    """Test cases for content generation functionality."""

    def test_generate_posts_structure(self):
        """Test that generate_posts returns correct structure."""
        if not os.getenv('GITHUB_TOKEN'):
            pytest.skip("GITHUB_TOKEN not configured")

        result = generate_posts("test topic", "", "")

        assert isinstance(result, dict)
        assert 'linkedin' in result
        assert 'facebook' in result
        assert 'instagram' in result
        assert 'hashtags' in result

    def test_generate_posts_respects_char_limits(self):
        """Test that posts respect character limits."""
        if not os.getenv('GITHUB_TOKEN'):
            pytest.skip("GITHUB_TOKEN not configured")

        result = generate_posts("AI trends", "", "")

        for platform, limit in CHAR_LIMITS.items():
            if platform in result:
                assert len(result[platform]) <= limit, f"{platform} exceeds {limit} chars"

    def test_save_posts(self, tmp_path):
        """Test saving posts to JSON file."""
        test_posts = {
            'linkedin': 'Test post',
            'facebook': 'Test post',
            'instagram': 'Test post',
            'hashtags': {
                'linkedin': ['#test'],
                'facebook': ['#test'],
                'instagram': ['#test']
            }
        }

        output_file = tmp_path / "test_posts.json"
        save_posts(test_posts, str(output_file))

        assert output_file.exists()

        with open(output_file, 'r') as f:
            loaded_data = json.load(f)

        assert loaded_data == test_posts


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
