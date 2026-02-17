#!/usr/bin/env python3
"""
Image Prompt Generation Tool

Generates optimized prompts for AI image generation based on social media post content.

Usage:
    python generate_image_prompt.py --posts-file .tmp/posts.json --output .tmp/image_prompt.txt
    python generate_image_prompt.py --posts-file posts.json --style "photorealistic" --output prompt.txt

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
    """Load posts from JSON file."""
    try:
        with open(posts_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise ValueError(f"Could not load posts file: {e}")


def generate_image_prompt(posts: Dict[str, Any], style: str = "modern professional") -> str:
    """
    Generate an optimized image prompt based on post content.

    Args:
        posts: Dictionary containing social media posts
        style: Desired visual style for the image

    Returns:
        Optimized prompt string for image generation

    Example:
        >>> prompt = generate_image_prompt(posts, "minimalist modern")
        >>> print(prompt)
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

    logger.info("Generating image prompt from posts")

    system_prompt = """You are an expert at creating prompts for AI image generation tools like Flux AI.
Your task is to create a detailed, specific prompt that will generate a high-quality image suitable
for social media posts.

Guidelines for good image prompts:
- Be specific about composition, lighting, colors, and style
- Include details about mood and atmosphere
- Specify image quality (e.g., "high resolution", "professional photography")
- Avoid text or words in the image (they rarely work well)
- Make it visually striking and social media-friendly
- Ensure the image will look good as a square or landscape format
- Consider the content of the posts when designing the visual

Output only the prompt text itself, no explanations or additional text."""

    user_prompt = f"""Based on these social media posts, create an optimized image generation prompt:

{json.dumps(posts, indent=2)}

Desired visual style: {style}

Create a detailed prompt that will generate a compelling image for these posts."""

    try:
        response = client.complete(
            messages=[
                SystemMessage(system_prompt),
                UserMessage(user_prompt)
            ],
            model=model,
            temperature=0.8,
            max_tokens=1024
        )

        prompt = response.choices[0].message.content.strip()

        logger.info("Image prompt generated successfully")
        logger.info(f"Prompt: {prompt}")

        return prompt

    except Exception as e:
        logger.error(f"Error during image prompt generation: {str(e)}")
        raise


def save_prompt(prompt: str, output_path: str):
    """
    Save image prompt to text file.

    Args:
        prompt: Image generation prompt
        output_path: Path to output text file
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(prompt)

    logger.info(f"Prompt saved to {output_path}")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Generate image prompts for social media posts'
    )
    parser.add_argument(
        '--posts-file',
        required=True,
        help='Path to posts JSON file'
    )
    parser.add_argument(
        '--style',
        default='modern professional',
        help='Desired visual style (default: modern professional)'
    )
    parser.add_argument(
        '--output',
        required=True,
        help='Output text file path for the prompt'
    )

    args = parser.parse_args()

    try:
        # Load posts
        posts = load_posts(args.posts_file)

        # Generate image prompt
        prompt = generate_image_prompt(posts, args.style)

        # Save prompt
        save_prompt(prompt, args.output)

        logger.info("Image prompt generation completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Image prompt generation failed: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
