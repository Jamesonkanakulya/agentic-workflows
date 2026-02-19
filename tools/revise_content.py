#!/usr/bin/env python3
"""
Content Revision Tool

Revises social media posts based on user feedback using GitHub's GPT-5 model.

Usage:
    python revise_content.py --posts-file .tmp/posts.json --feedback "Make it more casual" --output .tmp/posts.json
    python revise_content.py --posts-file posts.json --feedback "Add more statistics" --output revised_posts.json

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
from typing import Dict, Any

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


def load_posts(posts_file: str) -> Dict[str, Any]:
    """Load existing posts from JSON file."""
    try:
        with open(posts_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise ValueError(f"Could not load posts file: {e}")


def revise_posts(current_posts: Dict[str, Any], feedback: str) -> Dict[str, Any]:
    """
    Revise social media posts based on user feedback.

    Args:
        current_posts: Current version of the posts
        feedback: User feedback for revisions

    Returns:
        Dictionary containing revised posts

    Example:
        >>> revised = revise_posts(posts, "Make the tone more professional")
        >>> print(revised['linkedin'])
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

    logger.info(f"Revising content based on feedback: {feedback}")

    system_prompt = """You are an expert social media content editor. Your task is to revise
existing social media posts based on user feedback while maintaining platform-specific best practices.

Topic fidelity — this is the most important rule:
- Keep the revised posts fully focused on the original topic. Do NOT introduce AI, automation,
  or technology themes unless they were already present in the posts you are revising.
- Stay within the domain of the existing content (e.g. fitness stays fitness, food stays food).
- Only apply the changes the user explicitly requested — do not reframe or pivot the topic.

Guidelines:
- Apply the user's feedback to the relevant posts
- Maintain platform-appropriate tone (LinkedIn: professional, Facebook: conversational, Instagram: visual-focused)
- Keep each post ≤1900 characters
- Preserve the core message and domain while incorporating the feedback
- Ensure revised posts remain engaging and authentic to the topic

Output your response as a JSON object with the same structure as the input:
{
  "linkedin": "Revised LinkedIn post here...",
  "facebook": "Revised Facebook post here...",
  "instagram": "Revised Instagram caption here...",
  "hashtags": {
    "linkedin": ["#hashtag1", "#hashtag2"],
    "facebook": ["#hashtag1", "#hashtag2"],
    "instagram": ["#hashtag1", "#hashtag2"]
  }
}"""

    user_prompt = f"""Here are the current posts:

{json.dumps(current_posts, indent=2)}

User feedback: {feedback}

Please revise the posts according to this feedback while maintaining platform best practices."""

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
        if '```json' in content:
            start = content.find('```json') + 7
            end = content.find('```', start)
            content = content[start:end].strip()
        elif '```' in content:
            start = content.find('```') + 3
            end = content.find('```', start)
            content = content[start:end].strip()

        revised_posts = json.loads(content)

        # Validate character limits
        for platform, limit in CHAR_LIMITS.items():
            if platform in revised_posts and len(revised_posts[platform]) > limit:
                logger.warning(f"{platform} post exceeds {limit} chars, truncating...")
                revised_posts[platform] = revised_posts[platform][:limit-3] + "..."

        logger.info("Content revised successfully")
        return revised_posts

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        logger.error(f"Response content: {content}")
        raise
    except Exception as e:
        logger.error(f"Error during content revision: {str(e)}")
        raise


def save_posts(posts: Dict[str, Any], output_path: str):
    """
    Save revised posts to JSON file.

    Args:
        posts: Posts data to save
        output_path: Path to output JSON file
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)

    logger.info(f"Revised posts saved to {output_path}")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Revise social media content based on feedback'
    )
    parser.add_argument(
        '--posts-file',
        required=True,
        help='Path to existing posts JSON file'
    )
    parser.add_argument(
        '--feedback',
        required=True,
        help='User feedback for revisions'
    )
    parser.add_argument(
        '--output',
        required=True,
        help='Output JSON file path'
    )

    args = parser.parse_args()

    try:
        # Load current posts
        current_posts = load_posts(args.posts_file)

        # Revise content
        revised_posts = revise_posts(current_posts, args.feedback)

        # Save results
        save_posts(revised_posts, args.output)

        logger.info("Content revision completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Content revision failed: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
