# Social Media Workflow - GitHub GPT-5 Implementation

An AI-powered workflow for creating and posting social media content to LinkedIn, Facebook, and Instagram using GitHub's GPT-5 model. This implementation follows the WAT (Workflows, Agents, Tools) architecture.

## Overview

This workflow automates the process of:
1. Researching current trends on a topic
2. Generating platform-optimized content using GitHub's GPT-5
3. Creating custom images with Flux AI
4. Getting human approval before posting
5. Publishing to multiple social media platforms

## Architecture

```
workflows/              # Markdown SOPs (Standard Operating Procedures)
├── social_post_creator.md

tools/                  # Python scripts for deterministic execution
├── research_trends.py
├── generate_content.py
├── revise_content.py
├── generate_image_prompt.py
├── generate_image.py
├── upload_to_s3.py
├── post_to_platforms.py
└── tests/             # Test suite

.tmp/                  # Temporary files during workflow execution
```

## Features

- **Multi-Platform Support**: LinkedIn, Facebook, and Instagram
- **AI-Powered Content**: GitHub's GPT-5 for content generation
- **Image Generation**: Flux AI via Hugging Face
- **Trend Research**: Tavily API for current information
- **Human-in-the-Loop**: Approval and revision workflow
- **Platform Optimization**: Character limits and style per platform
- **Cloud Storage**: Cloudflare R2 integration for image hosting
- **Comprehensive Testing**: pytest suite for all tools

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy the template and fill in your API keys:

```bash
cp .env.template .env
# Edit .env with your actual credentials
```

Required API keys:
- **GITHUB_TOKEN**: Get from [GitHub Settings](https://github.com/settings/tokens)
- **TAVILY_API_KEY**: Get from [Tavily](https://tavily.com/)
- **HUGGINGFACE_API_TOKEN**: Get from [Hugging Face](https://huggingface.co/settings/tokens)
- **Cloudflare R2 Credentials**: For image storage (R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ACCOUNT_ID)
- **Social Media Tokens**: LinkedIn, Facebook, and Instagram API access

### 3. Run Tests

```bash
pytest tools/tests/ -v
```

## Usage

### Quick Start

Run the complete workflow interactively:

```bash
# 1. Research trends
python tools/research_trends.py \
  --topic "AI in healthcare" \
  --output .tmp/trends.json

# 2. Generate content
python tools/generate_content.py \
  --topic "AI in healthcare" \
  --trends-file .tmp/trends.json \
  --output .tmp/posts.json

# 3. Review the posts
cat .tmp/posts.json

# If revision needed:
python tools/revise_content.py \
  --posts-file .tmp/posts.json \
  --feedback "Make it more casual" \
  --output .tmp/posts.json

# 4. Generate image prompt
python tools/generate_image_prompt.py \
  --posts-file .tmp/posts.json \
  --output .tmp/image_prompt.txt

# 5. Generate image
python tools/generate_image.py \
  --prompt-file .tmp/image_prompt.txt \
  --output .tmp/post_image.png

# 6. Upload to Cloudflare R2
python tools/upload_to_s3.py \
  --file .tmp/post_image.png \
  --bucket n8nimages \
  --output .tmp/image_url.txt

# 7. Post to platforms
python tools/post_to_platforms.py \
  --posts-file .tmp/posts.json \
  --image-url-file .tmp/image_url.txt \
  --platforms linkedin facebook instagram \
  --output .tmp/post_results.json
```

### Individual Tools

Each tool can be run independently with `--help` for options:

```bash
python tools/research_trends.py --help
python tools/generate_content.py --help
# etc.
```

## Workflow Details

See [workflows/social_post_creator.md](workflows/social_post_creator.md) for the complete workflow SOP including:
- Step-by-step execution guide
- Success criteria for each step
- Error handling procedures
- Testing protocols

## Tool Documentation

### research_trends.py
Searches current trends using Tavily API.

**Input**: Topic string
**Output**: JSON with trends, insights, and sources

### generate_content.py
Creates platform-optimized posts using GitHub's GPT-5.

**Input**: Topic, trends data, optional context
**Output**: JSON with posts for LinkedIn, Facebook, Instagram

### revise_content.py
Revises posts based on user feedback.

**Input**: Existing posts, revision feedback
**Output**: Updated posts JSON

### generate_image_prompt.py
Creates optimized prompts for image generation.

**Input**: Post content
**Output**: Text prompt for Flux AI

### generate_image.py
Generates images using Flux AI via Hugging Face.

**Input**: Text prompt
**Output**: PNG image file

### upload_to_s3.py
Uploads files to Cloudflare R2 (S3-compatible storage).

**Input**: Image file
**Output**: Public URL

### post_to_platforms.py
Posts content to social media platforms.

**Input**: Posts JSON, image URL, platform list
**Output**: Results with post IDs and URLs

## Testing

Run the test suite:

```bash
# All tests
pytest tools/tests/ -v

# Specific test file
pytest tools/tests/test_research_trends.py -v

# With coverage report
pytest tools/tests/ --cov=tools --cov-report=html
```

Tests will skip automatically if API keys are not configured.

## Best Practices

1. **Always Test**: Run tests after creating or modifying tools
2. **Human Approval**: Never skip the approval step before posting
3. **Error Handling**: Tools implement retry logic and graceful failures
4. **Logging**: All tools log their operations for debugging
5. **Security**: Never commit `.env` file or expose API keys

## Comparison to n8n Workflow

This GitHub GPT-5 implementation mirrors the functionality of the n8n `social_post_creator` workflow but follows the WAT architecture:

| Feature | n8n | GitHub GPT-5 WAT |
|---------|-----|------------|
| Architecture | Visual node-based | Markdown SOPs + Python tools |
| Content Generation | AI agents in nodes | Separate Python tools |
| Approval Flow | Telegram trigger | Interactive CLI/script |
| Image Generation | Flux AI node | Dedicated Python tool |
| Platform Posting | Individual nodes | Unified posting tool |
| Testing | Manual | Automated pytest suite |
| Revision | Loop back mechanism | Dedicated revision tool |

## Troubleshooting

### API Errors
- Check `.env` file has correct API keys
- Verify API rate limits haven't been exceeded
- Check API service status

### Image Generation Fails
- Hugging Face model may be loading (wait and retry)
- Check prompt length and content
- Verify HUGGINGFACE_API_TOKEN is valid

### Platform Posting Issues
- Verify access tokens are current (they expire)
- Check required permissions for each platform
- Review API error messages in logs

## License

This workflow implementation is provided as-is for educational and commercial use.

## Contributing

When adding new tools:
1. Follow the existing tool structure
2. Add comprehensive docstrings
3. Create corresponding test file
4. Update this README
5. Run full test suite before committing
