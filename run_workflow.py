#!/usr/bin/env python3
"""
Social Media Workflow Runner

Interactive script to execute the social media post creation workflow.

Usage:
    python run_workflow.py
    python run_workflow.py --topic "AI trends" --platforms linkedin facebook
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60 + "\n")


def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ Error: {description} failed")
        print(f"Error output: {result.stderr}")
        return False

    print(f"✅ {description} completed successfully\n")
    return True


def display_json(file_path, title):
    """Display JSON file contents."""
    print_header(title)

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error reading file: {e}")


def get_user_approval():
    """Get user approval for posts."""
    print("\n" + "-" * 60)
    print("Review the posts above. What would you like to do?")
    print("  - Type 'approved' or 'APPROVED' to proceed with posting")
    print("  - Type 'cancel' to stop the workflow")
    print("  - Type any other feedback to request revisions")
    print("-" * 60)

    response = input("\nYour response: ").strip()
    return response


def main():
    """Main workflow execution."""
    parser = argparse.ArgumentParser(
        description='Run the social media workflow interactively'
    )
    parser.add_argument(
        '--topic',
        help='Topic for the social media posts'
    )
    parser.add_argument(
        '--context',
        default='',
        help='Additional context or requirements'
    )
    parser.add_argument(
        '--platforms',
        nargs='+',
        choices=['linkedin', 'facebook', 'instagram'],
        default=['linkedin', 'facebook', 'instagram'],
        help='Platforms to post to'
    )
    parser.add_argument(
        '--bucket',
        default='n8nimages',
        help='R2 bucket name'
    )
    parser.add_argument(
        '--skip-tests',
        action='store_true',
        help='Skip running tests'
    )

    args = parser.parse_args()

    # Welcome
    print_header("Social Media Workflow")
    print("This workflow will:")
    print("  1. Research current trends")
    print("  2. Generate platform-optimized content")
    print("  3. Get your approval")
    print("  4. Generate an image")
    print("  5. Post to social media platforms\n")

    # Get topic if not provided
    topic = args.topic
    if not topic:
        topic = input("Enter the topic for your social media posts: ").strip()
        if not topic:
            print("Error: Topic is required")
            return 1

    # Run tests first (unless skipped)
    if not args.skip_tests:
        print_header("Step 0: Running Tests")
        if not run_command(
            ['pytest', 'tools/tests/', '-v'],
            "Tool tests"
        ):
            response = input("Tests failed. Continue anyway? (y/n): ")
            if response.lower() != 'y':
                return 1

    # Step 1: Research trends
    print_header("Step 1: Researching Trends")
    if not run_command(
        ['python', 'tools/research_trends.py',
         '--topic', topic,
         '--output', '.tmp/trends.json'],
        "Trend research"
    ):
        return 1

    # Step 2: Generate content
    print_header("Step 2: Generating Content")
    cmd = [
        'python', 'tools/generate_content.py',
        '--topic', topic,
        '--trends-file', '.tmp/trends.json',
        '--output', '.tmp/posts.json'
    ]
    if args.context:
        cmd.extend(['--context', args.context])

    if not run_command(cmd, "Content generation"):
        return 1

    # Step 3: Review and approval loop
    approved = False
    while not approved:
        display_json('.tmp/posts.json', "Generated Posts")

        response = get_user_approval()

        if response.lower() in ['approved', 'approve']:
            approved = True
            print("\n✅ Posts approved! Continuing...\n")
        elif response.lower() == 'cancel':
            print("\n❌ Workflow cancelled by user.\n")
            return 0
        else:
            # Revise content
            print_header("Revising Content")
            if not run_command(
                ['python', 'tools/revise_content.py',
                 '--posts-file', '.tmp/posts.json',
                 '--feedback', response,
                 '--output', '.tmp/posts.json'],
                "Content revision"
            ):
                return 1

    # Step 4: Generate image prompt
    print_header("Step 4: Generating Image Prompt")
    if not run_command(
        ['python', 'tools/generate_image_prompt.py',
         '--posts-file', '.tmp/posts.json',
         '--output', '.tmp/image_prompt.txt'],
        "Image prompt generation"
    ):
        return 1

    # Step 5: Generate image
    print_header("Step 5: Generating Image")
    if not run_command(
        ['python', 'tools/generate_image.py',
         '--prompt-file', '.tmp/image_prompt.txt',
         '--output', '.tmp/post_image.png'],
        "Image generation"
    ):
        return 1

    # Step 6: Upload to S3
    print_header("Step 6: Uploading Image to S3")
    if not run_command(
        ['python', 'tools/upload_to_s3.py',
         '--file', '.tmp/post_image.png',
         '--bucket', args.bucket,
         '--output', '.tmp/image_url.txt'],
        "S3 upload"
    ):
        return 1

    # Step 7: Post to platforms
    print_header("Step 7: Posting to Social Media")

    # Final confirmation
    print(f"Ready to post to: {', '.join(args.platforms)}")
    final_confirm = input("Proceed with posting? (yes/no): ").strip().lower()

    if final_confirm != 'yes':
        print("\n❌ Posting cancelled by user.\n")
        return 0

    if not run_command(
        ['python', 'tools/post_to_platforms.py',
         '--posts-file', '.tmp/posts.json',
         '--image-url-file', '.tmp/image_url.txt',
         '--platforms'] + args.platforms +
        ['--output', '.tmp/post_results.json'],
        "Social media posting"
    ):
        return 1

    # Display results
    display_json('.tmp/post_results.json', "Posting Results")

    print_header("Workflow Complete!")
    print("✅ All tasks completed successfully")
    print(f"📊 Results saved to: .tmp/post_results.json\n")

    return 0


if __name__ == '__main__':
    sys.exit(main())
