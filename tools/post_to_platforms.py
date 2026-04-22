#!/usr/bin/env python3
"""
Social Media Posting Tool

Posts content to LinkedIn, Facebook, and Instagram with images.

Usage:
    python post_to_platforms.py --posts-file .tmp/posts.json --image-url-file .tmp/image_url.txt --platforms linkedin facebook instagram --output .tmp/post_results.json
    python post_to_platforms.py --posts-file posts.json --image-url "https://example.com/image.png" --platforms linkedin --output results.json

Requirements:
    - Platform-specific API credentials in .env file
    - pip install requests python-dotenv
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

import requests
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_environment():
    """Load environment variables from .env file."""
    load_dotenv(override=True)

    credentials = {
        'linkedin': {
            'access_token': os.getenv('LINKEDIN_ACCESS_TOKEN'),
            'person_urn': os.getenv('LINKEDIN_PERSON_URN')
        },
        'facebook': {
            'access_token': os.getenv('FACEBOOK_ACCESS_TOKEN'),
            'page_id': os.getenv('FACEBOOK_PAGE_ID')
        },
        'instagram': {
            'access_token': os.getenv('INSTAGRAM_ACCESS_TOKEN'),
            'user_id': os.getenv('INSTAGRAM_USER_ID')
        }
    }

    return credentials


def load_posts(posts_file: str) -> Dict[str, Any]:
    """Load posts from JSON file."""
    try:
        with open(posts_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise ValueError(f"Could not load posts file: {e}")


def load_image_url(image_url_file: Optional[str], image_url: Optional[str]) -> Optional[str]:
    """Load image URL from file or use provided URL."""
    if image_url:
        return image_url

    if image_url_file:
        try:
            with open(image_url_file, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception as e:
            logger.warning(f"Could not load image URL file: {e}")
            return None

    return None


def _linkedin_upload_image(access_token: str, person_urn: str, image_url: str) -> Optional[str]:
    """Upload an image to LinkedIn and return the asset URN."""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'X-Restli-Protocol-Version': '2.0.0'
    }

    # Step 1: Register the upload
    register_body = {
        'registerUploadRequest': {
            'recipes': ['urn:li:digitalmediaRecipe:feedshare-image'],
            'owner': person_urn,
            'serviceRelationships': [
                {'relationshipType': 'OWNER', 'identifier': 'urn:li:userGeneratedContent'}
            ]
        }
    }

    reg_resp = requests.post(
        'https://api.linkedin.com/v2/assets?action=registerUpload',
        headers=headers,
        json=register_body,
        timeout=30
    )

    if reg_resp.status_code not in [200, 201]:
        logger.error(f"LinkedIn image register failed: {reg_resp.status_code} {reg_resp.text}")
        return None

    reg_data = reg_resp.json()
    upload_url = reg_data['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
    asset_urn = reg_data['value']['asset']

    # Step 2: Download the image from our R2 URL
    img_resp = requests.get(image_url, timeout=30)
    if img_resp.status_code != 200:
        logger.error(f"Failed to download image from {image_url}: {img_resp.status_code}")
        return None

    # Step 3: Upload the binary to LinkedIn
    upload_resp = requests.put(
        upload_url,
        headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/octet-stream',
        },
        data=img_resp.content,
        timeout=60
    )

    if upload_resp.status_code not in [200, 201]:
        logger.error(f"LinkedIn image upload failed: {upload_resp.status_code} {upload_resp.text}")
        return None

    logger.info(f"LinkedIn image uploaded: {asset_urn}")
    return asset_urn


def post_to_linkedin(post_text: str, image_url: Optional[str], credentials: Dict) -> Dict[str, Any]:
    """
    Post to LinkedIn.

    Args:
        post_text: Text content for the post
        image_url: URL of the image to include
        credentials: LinkedIn API credentials

    Returns:
        Dictionary with post URL and ID
    """
    access_token = credentials.get('access_token')
    person_urn = credentials.get('person_urn')

    if not access_token or not person_urn:
        raise ValueError("LinkedIn credentials not configured")

    logger.info("Posting to LinkedIn...")

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'X-Restli-Protocol-Version': '2.0.0'
    }

    # Upload image to LinkedIn if provided
    media_category = 'NONE'
    media_list = []
    if image_url:
        asset_urn = _linkedin_upload_image(access_token, person_urn, image_url)
        if asset_urn:
            media_category = 'IMAGE'
            media_list = [{'status': 'READY', 'media': asset_urn}]
        else:
            logger.warning("Image upload failed, posting without image")

    # Build share content
    share_content = {
        'author': person_urn,
        'lifecycleState': 'PUBLISHED',
        'specificContent': {
            'com.linkedin.ugc.ShareContent': {
                'shareCommentary': {
                    'text': post_text
                },
                'shareMediaCategory': media_category
            }
        },
        'visibility': {
            'com.linkedin.ugc.MemberNetworkVisibility': 'PUBLIC'
        }
    }

    if media_list:
        share_content['specificContent']['com.linkedin.ugc.ShareContent']['media'] = media_list

    try:
        response = requests.post(
            'https://api.linkedin.com/v2/ugcPosts',
            headers=headers,
            json=share_content,
            timeout=30
        )

        if response.status_code in [200, 201]:
            post_id = response.json().get('id', '')
            logger.info(f"LinkedIn post created: {post_id}")
            return {
                'success': True,
                'platform': 'linkedin',
                'post_id': post_id,
                'url': f'https://www.linkedin.com/feed/update/{post_id}',
                'timestamp': datetime.now().isoformat()
            }
        else:
            logger.error(f"LinkedIn API error: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return {
                'success': False,
                'platform': 'linkedin',
                'error': response.text,
                'timestamp': datetime.now().isoformat()
            }

    except Exception as e:
        logger.error(f"Error posting to LinkedIn: {e}")
        return {
            'success': False,
            'platform': 'linkedin',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }


def post_to_facebook(post_text: str, image_url: Optional[str], credentials: Dict) -> Dict[str, Any]:
    """
    Post to Facebook.

    Args:
        post_text: Text content for the post
        image_url: URL of the image to include
        credentials: Facebook API credentials

    Returns:
        Dictionary with post URL and ID
    """
    access_token = credentials.get('access_token')
    page_id = credentials.get('page_id')

    if not access_token or not page_id:
        raise ValueError("Facebook credentials not configured")

    logger.info("Posting to Facebook...")

    params = {
        'access_token': access_token,
        'message': post_text
    }

    # Add image if provided
    if image_url:
        params['link'] = image_url

    try:
        response = requests.post(
            f'https://graph.facebook.com/v18.0/{page_id}/feed',
            params=params,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            post_id = data.get('id', '')
            logger.info(f"Facebook post created: {post_id}")
            return {
                'success': True,
                'platform': 'facebook',
                'post_id': post_id,
                'url': f'https://www.facebook.com/{post_id}',
                'timestamp': datetime.now().isoformat()
            }
        else:
            logger.error(f"Facebook API error: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return {
                'success': False,
                'platform': 'facebook',
                'error': response.text,
                'timestamp': datetime.now().isoformat()
            }

    except Exception as e:
        logger.error(f"Error posting to Facebook: {e}")
        return {
            'success': False,
            'platform': 'facebook',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }


def post_to_instagram(post_text: str, image_url: Optional[str], credentials: Dict) -> Dict[str, Any]:
    """
    Post to Instagram.

    Args:
        post_text: Caption for the post
        image_url: URL of the image (required for Instagram)
        credentials: Instagram API credentials

    Returns:
        Dictionary with post URL and ID
    """
    access_token = credentials.get('access_token')
    user_id = credentials.get('user_id')

    if not access_token or not user_id:
        raise ValueError("Instagram credentials not configured")

    if not image_url:
        raise ValueError("Image URL is required for Instagram posts")

    logger.info("Posting to Instagram...")

    try:
        # Step 1: Create media container
        container_params = {
            'access_token': access_token,
            'image_url': image_url,
            'caption': post_text
        }

        container_response = requests.post(
            f'https://graph.facebook.com/v18.0/{user_id}/media',
            params=container_params,
            timeout=30
        )

        if container_response.status_code != 200:
            logger.error(f"Instagram container creation error: {container_response.status_code}")
            logger.error(f"Response: {container_response.text}")
            return {
                'success': False,
                'platform': 'instagram',
                'error': container_response.text,
                'timestamp': datetime.now().isoformat()
            }

        container_id = container_response.json().get('id')

        # Step 2: Wait for media to be ready
        logger.info("Waiting for Instagram media to be processed...")
        time.sleep(5)

        # Step 3: Publish the media
        publish_params = {
            'access_token': access_token,
            'creation_id': container_id
        }

        publish_response = requests.post(
            f'https://graph.facebook.com/v18.0/{user_id}/media_publish',
            params=publish_params,
            timeout=30
        )

        if publish_response.status_code == 200:
            data = publish_response.json()
            post_id = data.get('id', '')
            logger.info(f"Instagram post created: {post_id}")
            return {
                'success': True,
                'platform': 'instagram',
                'post_id': post_id,
                'url': f'https://www.instagram.com/p/{post_id}/',
                'timestamp': datetime.now().isoformat()
            }
        else:
            logger.error(f"Instagram publish error: {publish_response.status_code}")
            logger.error(f"Response: {publish_response.text}")
            return {
                'success': False,
                'platform': 'instagram',
                'error': publish_response.text,
                'timestamp': datetime.now().isoformat()
            }

    except Exception as e:
        logger.error(f"Error posting to Instagram: {e}")
        return {
            'success': False,
            'platform': 'instagram',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }


def save_results(results: List[Dict[str, Any]], output_path: str):
    """
    Save posting results to JSON file.

    Args:
        results: List of posting results
        output_path: Path to output JSON file
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        'timestamp': datetime.now().isoformat(),
        'total_platforms': len(results),
        'successful': sum(1 for r in results if r.get('success')),
        'failed': sum(1 for r in results if not r.get('success')),
        'results': results
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    logger.info(f"Results saved to {output_path}")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Post content to social media platforms'
    )
    parser.add_argument(
        '--posts-file',
        required=True,
        help='Path to posts JSON file'
    )

    image_group = parser.add_mutually_exclusive_group()
    image_group.add_argument(
        '--image-url',
        help='Image URL to include in posts'
    )
    image_group.add_argument(
        '--image-url-file',
        help='Path to file containing image URL'
    )

    parser.add_argument(
        '--platforms',
        nargs='+',
        choices=['linkedin', 'facebook', 'instagram'],
        required=True,
        help='Platforms to post to'
    )
    parser.add_argument(
        '--output',
        required=True,
        help='Output JSON file path for results'
    )

    args = parser.parse_args()

    try:
        # Load credentials
        credentials = load_environment()

        # Load posts
        posts = load_posts(args.posts_file)

        # Load image URL
        image_url = load_image_url(args.image_url_file, args.image_url)

        if image_url:
            logger.info(f"Using image: {image_url}")
        else:
            logger.warning("No image URL provided")

        # Post to each platform
        results = []

        for platform in args.platforms:
            if platform not in posts:
                logger.warning(f"No post content found for {platform}")
                continue

            post_text = posts[platform]
            platform_creds = credentials.get(platform, {})

            try:
                if platform == 'linkedin':
                    result = post_to_linkedin(post_text, image_url, platform_creds)
                elif platform == 'facebook':
                    result = post_to_facebook(post_text, image_url, platform_creds)
                elif platform == 'instagram':
                    result = post_to_instagram(post_text, image_url, platform_creds)
                else:
                    continue

                results.append(result)

                # Rate limiting - wait between posts
                time.sleep(2)

            except ValueError as e:
                logger.error(f"Configuration error for {platform}: {e}")
                results.append({
                    'success': False,
                    'platform': platform,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Unexpected error posting to {platform}: {e}")
                results.append({
                    'success': False,
                    'platform': platform,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })

        # Save results
        save_results(results, args.output)

        # Log summary
        successful = sum(1 for r in results if r.get('success'))
        logger.info(f"Posting completed: {successful}/{len(results)} successful")

        # Return 0 only if all posts succeeded
        return 0 if successful == len(results) else 1

    except Exception as e:
        logger.error(f"Social media posting failed: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
