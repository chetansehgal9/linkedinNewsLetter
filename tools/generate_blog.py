#!/usr/bin/env python3
"""
Expand a LinkedIn draft into a full blog article using Claude.
Used for cross-posting to Medium and Dev.to.

Usage:
    python tools/generate_blog.py --draft-file .tmp/draft.json --output .tmp/blog.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()


SYSTEM_PROMPT = """You are a technical writer expanding a LinkedIn post into a full blog article for Medium and Dev.to.

## Your Job
Take the LinkedIn post (100-150 words) and expand it into a 500-800 word blog article.

## Requirements
- Use the LinkedIn post as the spine — same topic, same angle, same opinion
- Add depth: explain the *why* and *how*, give concrete examples, add context the LinkedIn format didn't allow
- Write in proper Markdown: use ## headings, **bold** for key terms, bullet lists where appropriate
- Opening paragraph must hook immediately — no "In this article I will..." intros
- Tone: direct, opinionated, technically credible — write for AI engineers and builders
- End with a clear takeaway or question (can reuse the LinkedIn CTA but expand it)
- Include a "## Key Takeaways" section near the end with 3 bullet points
- Do NOT pad with generic filler — every paragraph must earn its place
- Do NOT add an introduction like "This is an expanded version of my LinkedIn post"
- Content must be exclusively about AI

## Output Format
Return ONLY valid JSON with this exact shape:
{
  "title": "Full blog title — can be longer/more descriptive than the LinkedIn title",
  "body": "Full markdown article body",
  "tags": ["ai", "machinelearning", "llm"]
}

Tags must be 3-5 lowercase single-word strings suitable for Dev.to/Medium."""


def generate_blog(linkedin_draft: dict) -> dict:
    """
    Expand a LinkedIn draft into a full blog article.

    Args:
        linkedin_draft: The existing LinkedIn draft dict (title, body, hook, sources).

    Returns:
        Blog dict with title, body (markdown), and tags.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    li_title = linkedin_draft.get("title", "")
    li_body  = linkedin_draft.get("body", "")
    li_hook  = linkedin_draft.get("hook", "")
    li_cta   = linkedin_draft.get("cta", "")
    sources  = linkedin_draft.get("sources", {})

    news_lines = "\n".join(
        f"- {n.get('title', '')} — {n.get('url', '')}"
        for n in sources.get("news", [])
    )
    video_lines = "\n".join(
        f"- {v.get('title', '')} — {v.get('url', '')}"
        for v in sources.get("videos", [])
    )

    user_message = f"""Expand this LinkedIn post into a full blog article.

## LinkedIn Post
**Title:** {li_title}
**Hook:** {li_hook}
**Body:**
{li_body}
**CTA:** {li_cta}

## Sources Used
{news_lines or "_No news sources_"}
{video_lines or ""}

Write the expanded 500-800 word Markdown blog article. Return JSON as specified."""

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    text = next(
        (block.text for block in response.content if block.type == "text"), ""
    ).strip()

    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(l for l in lines if not l.strip().startswith("```"))

    try:
        blog = json.loads(text)
    except json.JSONDecodeError:
        blog = {
            "title": li_title,
            "body": text,
            "tags": ["ai", "machinelearning", "llm"],
        }

    return blog


def main():
    parser = argparse.ArgumentParser(description="Expand LinkedIn draft into blog article")
    parser.add_argument("--draft-file", required=True, help="Path to draft JSON file")
    parser.add_argument("--output", help="Save blog JSON to this file")
    args = parser.parse_args()

    draft = json.loads(Path(args.draft_file).read_text())
    blog = generate_blog(draft)

    output = json.dumps(blog, indent=2)
    print(output)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output)
        print(f"\nBlog saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
