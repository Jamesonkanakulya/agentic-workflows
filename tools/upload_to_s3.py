#!/usr/bin/env python3
"""
Cloudflare R2 Upload Tool

Uploads files to Cloudflare R2 (S3-compatible storage) and returns the public URL.

Usage:
    python upload_to_s3.py --file .tmp/post_image.png --bucket n8nimages --output .tmp/image_url.txt
    python upload_to_s3.py --file image.png --bucket n8nimages --key images/post.png --public --output url.txt

Requirements:
    - R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ACCOUNT_ID in .env file
    - pip install boto3 python-dotenv
"""

import argparse
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

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

    r2_access_key = os.getenv('R2_ACCESS_KEY_ID')
    r2_secret_key = os.getenv('R2_SECRET_ACCESS_KEY')
    r2_account_id = os.getenv('R2_ACCOUNT_ID')
    r2_bucket = os.getenv('R2_BUCKET', 'n8nimages')
    r2_public_url = os.getenv('R2_PUBLIC_URL', 'https://pub-1a28b7f568cf4a78856d9e19b0f64729.r2.dev')

    if not r2_access_key or not r2_secret_key or not r2_account_id:
        raise ValueError("Cloudflare R2 credentials not found. Required: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ACCOUNT_ID")

    return r2_access_key, r2_secret_key, r2_account_id, r2_bucket, r2_public_url


def archive_image_locally(file_path: str, topic: str = "") -> str:
    """
    Save a timestamped copy of the image to the local images/ archive directory.

    Args:
        file_path: Path to the source image file
        topic: Optional topic name to include in the filename

    Returns:
        Path to the archived local copy

    Example:
        >>> path = archive_image_locally(".tmp/post_image.png", "responsible_ai")
        >>> print(path)  # images/2026-02-16_153044_responsible_ai.png
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    ext = Path(file_path).suffix

    # Sanitize topic for use in filename
    if topic:
        safe_topic = "".join(c if c.isalnum() or c in "-_" else "_" for c in topic)
        safe_topic = safe_topic[:50]  # Limit length
        local_filename = f"{timestamp}_{safe_topic}{ext}"
    else:
        local_filename = f"{timestamp}{ext}"

    # Resolve images/ dir relative to this script's parent (project root)
    images_dir = Path(__file__).parent.parent / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    local_path = images_dir / local_filename
    shutil.copy2(file_path, local_path)

    logger.info(f"Image archived locally to {local_path}")
    return str(local_path)


def upload_to_s3(
    file_path: str,
    bucket: str,
    key: Optional[str] = None,
    public: bool = True,
    topic: str = ""
) -> str:
    """
    Archive image locally with a timestamped name, then upload to Cloudflare R2
    always as 'post_image.png' so the public URL remains constant.

    Args:
        file_path: Path to the file to upload
        bucket: R2 bucket name
        key: R2 object key — always overridden to 'post_image.png'
        public: Unused (R2 access controlled via bucket settings)
        topic: Optional topic used when naming the local archive copy

    Returns:
        Fixed public URL: https://pub-....r2.dev/post_image.png

    Example:
        >>> url = upload_to_s3(".tmp/post_image.png", "n8nimages", topic="responsible_ai")
        >>> print(url)  # https://pub-1a28b7f568cf4a78856d9e19b0f64729.r2.dev/post_image.png
    """
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
    except ImportError:
        raise ImportError("boto3 not installed. Run: pip install boto3")

    # Verify file exists
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    # Always upload as post_image.png so the public URL stays constant
    r2_key = "post_image.png"

    # Archive a local copy with a timestamped name before uploading
    archive_image_locally(file_path, topic)

    logger.info(f"Uploading {file_path} to r2://{bucket}/{r2_key}")

    try:
        # Initialize R2 client (S3-compatible)
        r2_access_key, r2_secret_key, r2_account_id, _, r2_public_url = load_environment()

        # Cloudflare R2 endpoint
        r2_endpoint = f"https://{r2_account_id}.r2.cloudflarestorage.com"

        s3_client = boto3.client(
            's3',
            aws_access_key_id=r2_access_key,
            aws_secret_access_key=r2_secret_key,
            endpoint_url=r2_endpoint,
            region_name='auto'
        )

        # Determine content type
        content_type = get_content_type(file_path)

        s3_client.upload_file(
            file_path,
            bucket,
            r2_key,
            ExtraArgs={'ContentType': content_type}
        )

        # Return the fixed public URL (R2 custom domain)
        url = f"{r2_public_url}/{r2_key}"

        logger.info(f"File uploaded successfully to Cloudflare R2 as '{r2_key}'")
        logger.info(f"Public URL: {url}")

        return url

    except NoCredentialsError:
        logger.error("Cloudflare R2 credentials not found or invalid")
        raise
    except ClientError as e:
        logger.error(f"Cloudflare R2 error: {e}")
        raise
    except Exception as e:
        logger.error(f"Error uploading to R2: {str(e)}")
        raise


def get_content_type(file_path: str) -> str:
    """Determine content type based on file extension."""
    ext = Path(file_path).suffix.lower()

    content_types = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.mp4': 'video/mp4',
        '.pdf': 'application/pdf',
        '.json': 'application/json',
        '.txt': 'text/plain'
    }

    return content_types.get(ext, 'application/octet-stream')


def save_url(url: str, output_path: str):
    """
    Save URL to text file.

    Args:
        url: URL to save
        output_path: Path to output text file
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(url)

    logger.info(f"URL saved to {output_path}")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Upload files to Cloudflare R2'
    )
    parser.add_argument(
        '--file',
        required=True,
        help='Path to file to upload'
    )
    parser.add_argument(
        '--bucket',
        required=True,
        help='R2 bucket name (default: n8nimages)'
    )
    parser.add_argument(
        '--key',
        help='R2 object key (ignored — always uploads as post_image.png)'
    )
    parser.add_argument(
        '--topic',
        default='',
        help='Topic used to name the local archive copy (optional)'
    )
    parser.add_argument(
        '--public',
        action='store_true',
        default=True,
        help='Make file publicly accessible (default: True)'
    )
    parser.add_argument(
        '--private',
        action='store_true',
        help='Make file private (overrides --public)'
    )
    parser.add_argument(
        '--output',
        required=True,
        help='Output file path for the URL'
    )

    args = parser.parse_args()

    # Handle public/private flag
    public = args.public and not args.private

    try:
        # Upload to R2
        url = upload_to_s3(
            args.file,
            args.bucket,
            args.key,
            public,
            args.topic
        )

        # Save URL
        save_url(url, args.output)

        logger.info("R2 upload completed successfully")
        return 0

    except Exception as e:
        logger.error(f"R2 upload failed: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
