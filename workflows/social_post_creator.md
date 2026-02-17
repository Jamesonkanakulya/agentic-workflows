# Social Post Creator Workflow

## Objective
Create engaging, platform-optimized social media posts for LinkedIn, Facebook, and Instagram with AI-generated content, images, and human-in-the-loop approval.

## Prerequisites
- Tavily API key for trend research
- GitHub token for AI content generation (GPT-5)
- Hugging Face API token for image generation (Flux AI)
- LinkedIn, Facebook, and Instagram API credentials
- Cloudflare R2 credentials (for image storage)

## Inputs
- `topic`: The subject/topic for the social media post (string)
- `additional_context`: Optional additional context or requirements (string, optional)

## Workflow Steps

### 1. Research Current Trends
**Tool**: `tools/research_trends.py`

**Objective**: Gather current information and trends related to the topic to ensure content is timely and relevant.

**Execution**:
```bash
python tools/research_trends.py --topic "{topic}" --output .tmp/trends.json
```

**Output**:
- `.tmp/trends.json`: Contains trend data, key insights, and relevant information

**Success Criteria**:
- Trends data is retrieved successfully
- JSON file contains at least 3 relevant insights
- No API errors from Tavily

### 2. Generate Platform-Specific Content
**Tool**: `tools/generate_content.py`

**Objective**: Create optimized social media posts for LinkedIn, Facebook, and Instagram using GitHub's GPT-5.

**Execution**:
```bash
python tools/generate_content.py \
  --topic "{topic}" \
  --trends-file .tmp/trends.json \
  --context "{additional_context}" \
  --output .tmp/posts.json
```

**Output**:
- `.tmp/posts.json`: Contains platform-specific posts with:
  - `linkedin`: Professional post (≤1900 chars)
  - `facebook`: Engaging post (≤1900 chars)
  - `instagram`: Visual-focused caption (≤1900 chars)
  - `hashtags`: Platform-appropriate hashtags

**Success Criteria**:
- All three posts are generated
- Each post respects character limits
- Posts are tailored to platform audience
- Content is engaging and on-brand

### 3. Present for Approval
**Tool**: Manual/Interactive

**Objective**: Display generated posts to user for review and approval.

**Execution**:
- Display contents of `.tmp/posts.json` to user
- Ask for feedback: "approved", "cancel", or revision instructions

**User Responses**:
- `approved` or `APPROVED` → Continue to Step 4
- `cancel` or `CANCEL` → End workflow
- Anything else → Treat as revision feedback, go to Step 3a

### 3a. Revise Content (if needed)
**Tool**: `tools/revise_content.py`

**Objective**: Update posts based on user feedback.

**Execution**:
```bash
python tools/revise_content.py \
  --posts-file .tmp/posts.json \
  --feedback "{user_feedback}" \
  --output .tmp/posts.json
```

**Output**:
- `.tmp/posts.json`: Updated with revised content

**Loop**: Return to Step 3 for re-approval

### 4. Generate Image Prompt
**Tool**: `tools/generate_image_prompt.py`

**Objective**: Create an optimized prompt for image generation based on approved content.

**Execution**:
```bash
python tools/generate_image_prompt.py \
  --posts-file .tmp/posts.json \
  --output .tmp/image_prompt.txt
```

**Output**:
- `.tmp/image_prompt.txt`: Optimized prompt for Flux AI

**Success Criteria**:
- Prompt is detailed and specific
- Includes visual style guidance
- Aligns with post content

### 5. Generate Image
**Tool**: `tools/generate_image.py`

**Objective**: Create a visual asset using Flux AI via Hugging Face.

**Execution**:
```bash
python tools/generate_image.py \
  --prompt-file .tmp/image_prompt.txt \
  --output .tmp/post_image.png
```

**Output**:
- `.tmp/post_image.png`: Generated image file

**Success Criteria**:
- Image is generated successfully
- Image meets quality standards
- File size is appropriate for social platforms

### 6. Upload Image to Cloudflare R2
**Tool**: `tools/upload_to_s3.py`

**Objective**: Store image in Cloudflare R2 cloud storage and get public URL.

**Execution**:
```bash
python tools/upload_to_s3.py \
  --file .tmp/post_image.png \
  --bucket "n8nimages" \
  --output .tmp/image_url.txt
```

**Output**:
- `.tmp/image_url.txt`: Public URL of uploaded image

**Success Criteria**:
- Image uploaded successfully to R2
- Public URL is accessible
- URL is stored for posting

### 7. Post to Social Platforms
**Tool**: `tools/post_to_platforms.py`

**Objective**: Publish approved content with image to all platforms.

**Execution**:
```bash
python tools/post_to_platforms.py \
  --posts-file .tmp/posts.json \
  --image-url-file .tmp/image_url.txt \
  --platforms linkedin facebook instagram \
  --output .tmp/post_results.json
```

**Output**:
- `.tmp/post_results.json`: Contains:
  - Post IDs for each platform
  - URLs to published posts
  - Timestamp
  - Success/failure status

**Success Criteria**:
- Posts published to all requested platforms
- No API errors
- Post URLs are accessible

## Final Outputs
- Published posts on LinkedIn, Facebook, and Instagram
- `.tmp/post_results.json`: Complete record of posting activity
- All posts include AI-generated image
- All posts are platform-optimized

## Error Handling
- **API Failures**: Retry with exponential backoff (max 3 attempts)
- **Content Generation Issues**: Notify user, allow manual content input
- **Image Generation Failures**: Use fallback stock image or retry
- **Platform Posting Errors**: Log error, continue with other platforms

## Testing Protocol
Before considering this workflow complete:
1. Run all tool tests: `pytest tools/tests/`
2. Execute end-to-end workflow test with sample topic
3. Verify posts on all three platforms
4. Test revision workflow
5. Test cancellation workflow
6. Verify error handling scenarios

## Success Metrics
- All tools pass their individual tests
- End-to-end workflow completes successfully
- Posts appear correctly on all platforms
- Images are properly formatted and displayed
- Character limits are respected
- Revision workflow functions correctly

## Notes
- All API keys must be configured in `.env` file
- Tools are deterministic Python scripts (no AI reasoning in tools)
- AI reasoning happens in content/image prompt generation only
- Human approval is mandatory before posting
- Images are cached in Cloudflare R2 for future reference
- All intermediate files stored in `.tmp/` directory
