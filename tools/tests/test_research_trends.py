#!/usr/bin/env python3
"""
Tests for research_trends.py

Run with: pytest tools/tests/test_research_trends.py -v
"""

import json
import os
import sys
from pathlib import Path
import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from research_trends import research_trends, save_results


class TestResearchTrends:
    """Test cases for trend research functionality."""

    def test_research_trends_returns_data(self):
        """Test that research_trends returns valid data structure."""
        # Skip if no API key
        if not os.getenv('TAVILY_API_KEY'):
            pytest.skip("TAVILY_API_KEY not configured")

        result = research_trends("artificial intelligence", max_results=2)

        assert isinstance(result, dict)
        assert 'topic' in result
        assert 'summary' in result
        assert 'insights' in result
        assert 'sources' in result
        assert result['topic'] == "artificial intelligence"

    def test_research_trends_insights_structure(self):
        """Test that insights have correct structure."""
        if not os.getenv('TAVILY_API_KEY'):
            pytest.skip("TAVILY_API_KEY not configured")

        result = research_trends("climate change", max_results=1)

        assert len(result['insights']) > 0
        insight = result['insights'][0]
        assert 'title' in insight
        assert 'content' in insight
        assert 'url' in insight

    def test_save_results(self, tmp_path):
        """Test saving results to JSON file."""
        test_data = {
            'topic': 'test',
            'summary': 'test summary',
            'insights': [],
            'sources': []
        }

        output_file = tmp_path / "test_trends.json"
        save_results(test_data, str(output_file))

        assert output_file.exists()

        with open(output_file, 'r') as f:
            loaded_data = json.load(f)

        assert loaded_data == test_data


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
