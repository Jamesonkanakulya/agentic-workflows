#!/usr/bin/env python3
"""
Pytest configuration and fixtures for tool tests.
"""

import os
import pytest
from dotenv import load_dotenv

# Load environment variables before tests
load_dotenv()


@pytest.fixture(scope="session")
def sample_posts():
    """Sample posts data for testing."""
    return {
        'linkedin': 'Professional post about AI trends in 2024.',
        'facebook': 'Engaging post about AI developments!',
        'instagram': 'AI is transforming our world! #AI #Tech',
        'hashtags': {
            'linkedin': ['#AI', '#Technology', '#Innovation'],
            'facebook': ['#ArtificialIntelligence', '#Tech'],
            'instagram': ['#AI', '#Tech', '#Innovation', '#Future']
        }
    }


@pytest.fixture(scope="session")
def sample_trends():
    """Sample trends data for testing."""
    return {
        'topic': 'artificial intelligence',
        'summary': 'AI is rapidly evolving with new developments.',
        'insights': [
            {
                'title': 'AI Breakthrough',
                'content': 'Recent advances in AI technology.',
                'score': 0.95,
                'url': 'https://example.com/ai-news'
            }
        ],
        'sources': ['https://example.com/ai-news'],
        'total_results': 1
    }


@pytest.fixture
def skip_if_no_api_keys():
    """Skip test if API keys are not configured."""
    required_keys = [
        'TAVILY_API_KEY',
        'GITHUB_TOKEN',
        'HUGGINGFACE_API_TOKEN'
    ]

    missing_keys = [key for key in required_keys if not os.getenv(key)]

    if missing_keys:
        pytest.skip(f"Missing API keys: {', '.join(missing_keys)}")
