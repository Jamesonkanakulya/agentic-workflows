#!/usr/bin/env python3
"""
Content Generation Tool

Generates platform-optimized social media posts using GitHub's GPT-5 model.

Usage:
    python generate_content.py --topic "AI trends" --trends-file .tmp/trends.json --output .tmp/posts.json
    python generate_content.py --topic "Climate change" --context "Focus on solutions" --output posts.json

Requirements:
    - GITHUB_TOKEN in .env file
    - pip install azure-ai-inference python-dotenv
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional

from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Character limits for each platform
CHAR_LIMITS = {
    'linkedin': 1900,
    'facebook': 1900,
    'instagram': 1900
}


def load_environment():
    """Load environment variables from .env file."""
    load_dotenv()
    token = os.getenv('GITHUB_TOKEN')
    endpoint = os.getenv('GITHUB_ENDPOINT', 'https://models.github.ai/inference')
    model = os.getenv('GITHUB_MODEL', 'openai/gpt-5')

    if not token:
        logger.error("GITHUB_TOKEN not found in environment variables")
        sys.exit(1)

    return token, endpoint, model


def load_trends(trends_file: Optional[str]) -> str:
    """Load trend data from JSON file if provided."""
    if not trends_file:
        return ""

    try:
        with open(trends_file, 'r', encoding='utf-8') as f:
            trends = json.load(f)
            return f"\n\nCurrent Trends:\n{json.dumps(trends, indent=2)}"
    except Exception as e:
        logger.warning(f"Could not load trends file: {e}")
        return ""


def generate_posts(topic: str, trends_context: str, additional_context: str = "") -> Dict[str, Any]:
    """
    Generate platform-specific social media posts using GitHub's GPT-5 model.

    Args:
        topic: Main topic for the posts
        trends_context: Context from trend research
        additional_context: Additional user-provided context

    Returns:
        Dictionary containing posts for each platform

    Example:
        >>> posts = generate_posts("AI in healthcare", trends_data, "Focus on benefits")
        >>> print(posts['linkedin'])
    """
    try:
        from azure.ai.inference import ChatCompletionsClient
        from azure.ai.inference.models import SystemMessage, UserMessage
        from azure.core.credentials import AzureKeyCredential
    except ImportError:
        logger.error("azure-ai-inference not installed. Run: pip install azure-ai-inference")
        sys.exit(1)

    token, endpoint, model = load_environment()

    client = ChatCompletionsClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(token),
    )

    logger.info(f"Generating content for topic: {topic}")

    system_prompt = """You are an expert social media content creator. Your task is to create engaging,
platform-optimized posts for LinkedIn, Facebook, and Instagram.

Guidelines:
- LinkedIn: Professional tone, industry insights, thought leadership
- Facebook: Conversational and engaging, encourage discussion
- Instagram: Visual-focused, concise with strong call-to-action

Requirements:
- Each post must be ≤1900 characters
- Include relevant hashtags (3-5 per platform)
- Use platform-appropriate language and style
- Ensure posts are engaging and on-brand
- Include call-to-action where appropriate

Output your response as a JSON object with this exact structure:
{
  "linkedin": "Your LinkedIn post here...",
  "facebook": "Your Facebook post here...",
  "instagram": "Your Instagram caption here...",
  "hashtags": {
    "linkedin": ["#hashtag1", "#hashtag2"],
    "facebook": ["#hashtag1", "#hashtag2"],
    "instagram": ["#hashtag1", "#hashtag2"]
  }
}"""

    user_prompt = f"""Create social media posts about: {topic}

{additional_context}
{trends_context}

Generate engaging posts for LinkedIn, Facebook, and Instagram following the guidelines."""

    try:
        response = client.complete(
            messages=[
                SystemMessage(system_prompt),
                UserMessage(user_prompt)
            ],
            model=model,
            temperature=0.7,
            max_tokens=4096
        )

        # Extract text content
        content = response.choices[0].message.content

        # Try to extract JSON from the response
        # Handle cases where Claude might wrap JSON in markdown code blocks
        if '```json' in content:
            start = content.find('```json') + 7
            end = content.find('```', start)
            content = content[start:end].strip()
        elif '```' in content:
            start = content.find('```') + 3
            end = content.find('```', start)
            content = content[start:end].strip()

        posts = json.loads(content)

        # Validate character limits
        for platform, limit in CHAR_LIMITS.items():
            if platform in posts and len(posts[platform]) > limit:
                logger.warning(f"{platform} post exceeds {limit} chars, truncating...")
                posts[platform] = posts[platform][:limit-3] + "..."

        logger.info("Content generated successfully")
        return posts

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        logger.error(f"Response content: {content}")
        raise
    except Exception as e:
        logger.error(f"Error during content generation: {str(e)}")
        raise


def save_posts(posts: Dict[str, Any], output_path: str):
    """
    Save generated posts to JSON file.

    Args:
        posts: Posts data to save
        output_path: Path to output JSON file
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)

    logger.info(f"Posts saved to {output_path}")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Generate social media content using Claude AI'
    )
    parser.add_argument(
        '--topic',
        required=True,
        help='Topic for the social media posts'
    )
    parser.add_argument(
        '--trends-file',
        help='Path to trends JSON file (optional)'
    )
    parser.add_argument(
        '--context',
        default='',
        help='Additional context or requirements (optional)'
    )
    parser.add_argument(
        '--output',
        required=True,
        help='Output JSON file path'
    )

    args = parser.parse_args()

    try:
        # Load trends if provided
        trends_context = load_trends(args.trends_file)

        # Generate content
        posts = generate_posts(args.topic, trends_context, args.context)

        # Save results
        save_posts(posts, args.output)

        logger.info("Content generation completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Content generation failed: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
