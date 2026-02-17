#!/usr/bin/env python3
"""
Image Generation Tool

Generates images using Flux AI via Hugging Face Inference API.

Usage:
    python generate_image.py --prompt-file .tmp/image_prompt.txt --output .tmp/post_image.png
    python generate_image.py --prompt "A beautiful sunset" --output image.png --width 1024 --height 1024

Requirements:
    - HUGGINGFACE_API_TOKEN in .env file
    - pip install requests python-dotenv pillow
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Hugging Face Flux model endpoint (using Router API - matches n8n config)
FLUX_MODEL = "black-forest-labs/FLUX.1-schnell"
API_URL = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"


def load_environment():
    """Load environment variables from .env file."""
    load_dotenv()
    api_token = os.getenv('HUGGINGFACE_API_TOKEN')
    if not api_token:
        logger.error("HUGGINGFACE_API_TOKEN not found in environment variables")
        sys.exit(1)
    return api_token


def load_prompt(prompt_file: Optional[str], prompt_text: Optional[str]) -> str:
    """Load prompt from file or use provided text."""
    if prompt_text:
        return prompt_text

    if prompt_file:
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception as e:
            logger.error(f"Could not load prompt file: {e}")
            sys.exit(1)

    logger.error("Either --prompt or --prompt-file must be provided")
    sys.exit(1)


def generate_image(
    prompt: str,
    api_token: str,
    width: int = 1024,
    height: int = 1024,
    max_retries: int = 3
) -> bytes:
    """
    Generate an image using Flux AI via Hugging Face.

    Args:
        prompt: Text prompt for image generation
        api_token: Hugging Face API token
        width: Image width in pixels
        height: Image height in pixels
        max_retries: Maximum number of retry attempts

    Returns:
        Image data as bytes

    Example:
        >>> image_data = generate_image("A serene landscape", token)
        >>> with open("output.png", "wb") as f:
        >>>     f.write(image_data)
    """
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "image/jpeg"  # Matches n8n configuration
    }

    payload = {
        "inputs": prompt,
        "parameters": {
            "width": width,
            "height": height,
            "num_inference_steps": 4  # Schnell model uses 4 steps
        }
    }

    logger.info(f"Generating image with prompt: {prompt[:100]}...")

    for attempt in range(max_retries):
        try:
            response = requests.post(
                API_URL,
                headers=headers,
                json=payload,
                timeout=60
            )

            if response.status_code == 200:
                logger.info("Image generated successfully")
                return response.content

            elif response.status_code == 503:
                # Model is loading, wait and retry
                logger.warning("Model is loading, waiting to retry...")
                wait_time = min(20 * (attempt + 1), 60)
                time.sleep(wait_time)
                continue

            else:
                logger.error(f"API request failed: {response.status_code}")
                logger.error(f"Response: {response.text}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying... (attempt {attempt + 2}/{max_retries})")
                    time.sleep(5)
                else:
                    raise Exception(f"Image generation failed: {response.text}")

        except requests.exceptions.Timeout:
            logger.warning(f"Request timed out (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                raise Exception("Image generation timed out after multiple attempts")

        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Error on attempt {attempt + 1}: {e}")
                time.sleep(5)
            else:
                raise

    raise Exception("Image generation failed after all retry attempts")


def save_image(image_data: bytes, output_path: str):
    """
    Save image data to file.

    Args:
        image_data: Image bytes
        output_path: Path to output image file
    """
    try:
        from PIL import Image
        import io

        # Open and verify the image
        img = Image.open(io.BytesIO(image_data))

        # Ensure output directory exists
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Save the image
        img.save(output_file, format='PNG', optimize=True)

        logger.info(f"Image saved to {output_path}")
        logger.info(f"Image size: {img.size[0]}x{img.size[1]}")

    except Exception as e:
        logger.error(f"Error saving image: {e}")
        # Fallback: save raw bytes
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'wb') as f:
            f.write(image_data)
        logger.info(f"Image saved as raw bytes to {output_path}")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Generate images using Flux AI'
    )

    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument(
        '--prompt',
        help='Text prompt for image generation'
    )
    prompt_group.add_argument(
        '--prompt-file',
        help='Path to file containing the prompt'
    )

    parser.add_argument(
        '--output',
        required=True,
        help='Output image file path (PNG format)'
    )
    parser.add_argument(
        '--width',
        type=int,
        default=1024,
        help='Image width in pixels (default: 1024)'
    )
    parser.add_argument(
        '--height',
        type=int,
        default=1024,
        help='Image height in pixels (default: 1024)'
    )
    parser.add_argument(
        '--max-retries',
        type=int,
        default=3,
        help='Maximum retry attempts (default: 3)'
    )

    args = parser.parse_args()

    try:
        # Load API token
        api_token = load_environment()

        # Load prompt
        prompt = load_prompt(args.prompt_file, args.prompt)

        # Generate image
        image_data = generate_image(
            prompt,
            api_token,
            args.width,
            args.height,
            args.max_retries
        )

        # Save image
        save_image(image_data, args.output)

        logger.info("Image generation completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Image generation failed: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
