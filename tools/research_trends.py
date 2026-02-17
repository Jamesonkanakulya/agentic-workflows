#!/usr/bin/env python3
"""
Trend Research Tool

Researches current trends and information related to a topic using Tavily API.

Usage:
    python research_trends.py --topic "AI in healthcare" --output .tmp/trends.json
    python research_trends.py --topic "sustainable fashion" --max-results 5 --output trends.json

Requirements:
    - TAVILY_API_KEY in .env file
    - pip install tavily-python python-dotenv
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Any

from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_environment():
    """Load environment variables from .env file."""
    load_dotenv()
    api_key = os.getenv('TAVILY_API_KEY')
    if not api_key:
        raise ValueError("TAVILY_API_KEY not found in environment variables")
    return api_key


def research_trends(topic: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Research trends and current information about a topic.

    Args:
        topic: The topic to research
        max_results: Maximum number of search results to return

    Returns:
        Dictionary containing trend data and insights

    Example:
        >>> results = research_trends("sustainable fashion", max_results=3)
        >>> print(results['insights'])
    """
    try:
        from tavily import TavilyClient
    except ImportError:
        raise ImportError("tavily-python not installed. Run: pip install tavily-python")

    api_key = load_environment()
    client = TavilyClient(api_key=api_key)

    logger.info(f"Researching trends for topic: {topic}")

    try:
        # Search for current information and trends
        response = client.search(
            query=f"current trends and latest information about {topic}",
            max_results=max_results,
            search_depth="advanced",
            include_answer=True,
            include_raw_content=False
        )

        # Extract key information
        insights = []
        sources = []

        if 'results' in response:
            for result in response['results']:
                insights.append({
                    'title': result.get('title', ''),
                    'content': result.get('content', ''),
                    'score': result.get('score', 0),
                    'url': result.get('url', '')
                })
                sources.append(result.get('url', ''))

        trends_data = {
            'topic': topic,
            'summary': response.get('answer', 'No summary available'),
            'insights': insights,
            'sources': sources,
            'total_results': len(insights)
        }

        logger.info(f"Successfully retrieved {len(insights)} insights")
        return trends_data

    except Exception as e:
        logger.error(f"Error during Tavily search: {str(e)}")
        raise


def save_results(data: Dict[str, Any], output_path: str):
    """
    Save research results to JSON file.

    Args:
        data: Research data to save
        output_path: Path to output JSON file
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"Results saved to {output_path}")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Research trends using Tavily API'
    )
    parser.add_argument(
        '--topic',
        required=True,
        help='Topic to research'
    )
    parser.add_argument(
        '--max-results',
        type=int,
        default=5,
        help='Maximum number of results (default: 5)'
    )
    parser.add_argument(
        '--output',
        required=True,
        help='Output JSON file path'
    )

    args = parser.parse_args()

    try:
        # Research trends
        results = research_trends(args.topic, args.max_results)

        # Save results
        save_results(results, args.output)

        logger.info("Trend research completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Trend research failed: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
