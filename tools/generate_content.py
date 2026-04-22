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
import re
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
        raise ValueError("GITHUB_TOKEN not found in environment variables")

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


def clean_post_text(text: str) -> str:
    """Normalize model output into clean paragraph text."""
    cleaned = (text or "").strip()
    cleaned = re.sub(r"[*_`#]+", "", cleaned)
    cleaned = re.sub(r"^[\-\u2022]+\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


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
        raise ImportError("azure-ai-inference not installed. Run: pip install azure-ai-inference")

    token, endpoint, model = load_environment()

    client = ChatCompletionsClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(token),
    )

    logger.info(f"Generating content for topic: {topic}")

    system_prompt = """You are an expert social media content creator. Your task is to create engaging,
platform-optimized posts for LinkedIn, Facebook, and Instagram.

Topic fidelity — this is the most important rule:
- Write exclusively about the topic given. Do NOT inject AI, automation, or technology themes
  unless the topic itself is explicitly about those subjects.
- Understand the domain of the topic (e.g. fitness, food, finance, travel, health, real estate,
  fashion, sports, etc.) and write content that feels native to that domain.
- Use the trend research as supporting context and data points — not as a reason to pivot the topic.
- The post should sound like it was written by a genuine expert in the topic's field.

Platform guidelines:
- LinkedIn: Professional tone, industry insights, thought leadership relevant to the topic
- Facebook: Conversational and engaging, encourage discussion around the topic
- Instagram: Visual-focused, concise caption with strong call-to-action tied to the topic

Requirements:
- Each post must be ≤1900 characters
- Include 3-5 relevant hashtags per platform that match the topic's domain
- Use platform-appropriate language and style
- Ensure posts are engaging and feel authentic to the topic
- Write in clean plain-text paragraphs only
- Do not use markdown, bold markers, bullets, headings, or surrounding quotation marks
- Do not include **, __, backticks, or list formatting inside the post text

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

Write posts that are fully focused on the topic above. Stay in the topic's domain and use the
trend research as supporting context only. Be creative and fresh, but return clean paragraph text for LinkedIn, Facebook, and Instagram."""

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

        for platform in CHAR_LIMITS:
            if platform in posts:
                posts[platform] = clean_post_text(posts[platform])

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
