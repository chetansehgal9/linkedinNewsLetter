#!/usr/bin/env python3
"""
Generate a LinkedIn post draft using the Claude API.
Reads your writing style from workflows/writing_style.md and crafts a post
that connects your latest YouTube video(s) with relevant news.

Usage:
    python tools/generate_draft.py \
        --videos '[{"title":"...", "url":"...", "description":"..."}]' \
        --news '[{"title":"...", "summary":"...", "url":"..."}]'

    python tools/generate_draft.py \
        --videos-file .tmp/videos.json \
        --news-file .tmp/news.json \
        --output .tmp/draft.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

STYLE_FILE = Path(__file__).parent.parent / "workflows" / "writing_style.md"


def load_writing_style() -> str:
    if STYLE_FILE.exists():
        return STYLE_FILE.read_text()
    return "Write in a professional but conversational tone. Be concise and insightful."


def build_system_prompt(writing_style: str) -> str:
    return f"""You are a ghostwriter helping craft LinkedIn newsletter posts.

## Writing Style Guide
{writing_style}

## Post Requirements
- Length: 150–300 words (LinkedIn sweet spot for engagement)
- Structure: Hook → Insight → Call to action
- Tone: Match the style guide above exactly
- Include 3–5 relevant hashtags at the end
- If a YouTube video is provided, weave it in naturally (don't just say "check out my video")
- Connect the video content to current news/trends to show relevance
- End with a question or CTA that invites comments
- Do NOT use generic opener phrases like "In today's fast-paced world..." or "I'm excited to share..."
- Do NOT use excessive emojis — max 2–3 total

## Output Format
Return ONLY valid JSON with this exact shape:
{{
  "title": "Short headline for the newsletter article (max 10 words)",
  "body": "The full post text, ready to publish",
  "hashtags": ["tag1", "tag2", "tag3"],
  "hook": "First sentence — the attention-grabber",
  "cta": "The call-to-action line"
}}"""


def generate_draft(
    videos: list[dict],
    news_items: list[dict],
    writing_style: str | None = None,
    feedback: str | None = None,
) -> dict:
    """Generate a LinkedIn post draft using Claude.

    Args:
        videos: YouTube video metadata dicts.
        news_items: News article metadata dicts.
        writing_style: Override the default writing style guide.
        feedback: Optional revision instructions from a previous draft rejection.
                  When provided, Claude rewrites using the same sources but applies
                  the feedback (e.g. "make it shorter, focus on enterprise use cases").
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    style = writing_style or load_writing_style()

    # Build user message
    video_section = ""
    if videos:
        video_lines = []
        for v in videos[:2]:  # max 2 videos per post
            video_lines.append(
                f"- Title: {v.get('title', '')}\n"
                f"  URL: {v.get('url', '')}\n"
                f"  Description: {v.get('description', '')[:400]}"
            )
        video_section = "## My Latest YouTube Video(s)\n" + "\n".join(video_lines)

    news_section = ""
    if news_items:
        news_lines = []
        for n in news_items[:5]:  # max 5 news items for context
            news_lines.append(
                f"- {n.get('title', '')} ({n.get('source', '')})\n"
                f"  {n.get('summary', '')[:200]}"
            )
        news_section = "## Relevant News / Trends\n" + "\n".join(news_lines)

    feedback_section = ""
    if feedback:
        feedback_section = f"""## Revision Feedback
The previous draft was not approved. Rewrite the post using the same sources above,
but incorporate this feedback:

{feedback.strip()}

"""

    user_message = f"""Please write a LinkedIn newsletter post based on the following context.

{video_section}

{news_section}

{feedback_section}Create a post that:
1. Leads with the most compelling angle from the video + news combination
2. Teaches something concrete (a insight, framework, or perspective)
3. Connects the video to the broader trend shown in the news
4. Invites engagement with a specific question

Return the JSON as specified."""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2000,
        thinking={"type": "adaptive"},
        system=build_system_prompt(style),
        messages=[{"role": "user", "content": user_message}],
    )

    # Extract text block
    text = next(
        (block.text for block in response.content if block.type == "text"),
        "",
    )

    # Parse JSON from response
    text = text.strip()
    if text.startswith("```"):
        # Strip markdown code fences
        lines = text.split("\n")
        text = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        )

    try:
        draft = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: return raw text wrapped in our schema
        draft = {
            "title": "New Post",
            "body": text,
            "hashtags": [],
            "hook": "",
            "cta": "",
        }

    # Enrich with source metadata
    draft["sources"] = {
        "videos": [{"title": v.get("title"), "url": v.get("url")} for v in videos],
        "news": [{"title": n.get("title"), "url": n.get("url")} for n in news_items[:3]],
    }
    draft["model"] = "claude-opus-4-6"
    draft["usage"] = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    return draft


def main():
    parser = argparse.ArgumentParser(description="Generate LinkedIn post draft via Claude")
    parser.add_argument("--videos", help="JSON array of video objects")
    parser.add_argument("--news", help="JSON array of news objects")
    parser.add_argument("--videos-file", help="Path to JSON file with videos")
    parser.add_argument("--news-file", help="Path to JSON file with news")
    parser.add_argument("--output", help="Save draft JSON to this file")
    args = parser.parse_args()

    videos = []
    news_items = []

    if args.videos:
        videos = json.loads(args.videos)
    elif args.videos_file:
        videos = json.loads(Path(args.videos_file).read_text())

    if args.news:
        news_items = json.loads(args.news)
    elif args.news_file:
        news_items = json.loads(Path(args.news_file).read_text())

    if not videos and not news_items:
        print("ERROR: Provide at least --videos or --news (or file variants)", file=sys.stderr)
        sys.exit(1)

    draft = generate_draft(videos, news_items)
    output = json.dumps(draft, indent=2)
    print(output)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output)
        print(f"\nDraft saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
