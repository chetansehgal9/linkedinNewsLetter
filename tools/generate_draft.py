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

STYLE_FILE        = Path(__file__).parent.parent / "workflows" / "writing_style.md"
POSTED_TOPICS_FILE = Path(__file__).parent.parent / "assets" / "posted_topics.txt"


def load_posted_topics() -> list[str]:
    """Load previously posted topics to avoid repetition."""
    if POSTED_TOPICS_FILE.exists():
        lines = POSTED_TOPICS_FILE.read_text().strip().splitlines()
        return [l.strip() for l in lines if l.strip()]
    return []


def record_posted_topic(title: str) -> None:
    """Append a new post title to the tracking file (keep last 10)."""
    topics = load_posted_topics()
    topics.append(title)
    topics = topics[-10:]  # keep last 10 only
    POSTED_TOPICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    POSTED_TOPICS_FILE.write_text("\n".join(topics) + "\n")


def load_writing_style() -> str:
    if STYLE_FILE.exists():
        return STYLE_FILE.read_text()
    return "Write in a professional but conversational tone. Be concise and insightful."


def build_system_prompt(writing_style: str) -> str:
    return f"""You are a ghostwriter helping craft LinkedIn posts about AI.

## Writing Style Guide
{writing_style}

## Content Focus
Write EXCLUSIVELY about artificial intelligence: LLMs, AI agents, model releases, inference
infrastructure, AI safety, prompt engineering, RAG, fine-tuning, multimodal models, AI product
decisions, AI research papers, or how AI is changing how engineers and builders work.
If the provided sources are not about AI, pick the angle that is closest to AI and frame it
through an AI lens. Do NOT write about general software engineering, cloud infra, or other tech
topics unless they are directly tied to an AI use case or AI system design.

## Post Requirements
- Length: 100–150 words (tight, punchy — every sentence must earn its place)
- Structure: Sharp observation → AI-specific insight → Practical takeaway or question
- Lead with a specific, concrete claim about an AI model, tool, behaviour, or tradeoff — NOT a narrative
- Tone: Direct, opinionated, technically credible. Write for engineers and builders who work with AI.
- Include 3–5 AI-focused hashtags at the end (#AI #LLM #GenerativeAI #AIEngineering #MachineLearning etc.)
- If a YouTube video is provided, extract the core AI idea and make that the post's spine
- End with a pointed question or concrete takeaway for an AI-practitioner audience
- Prioritise the most recently published news item as your primary source angle
- If a news item was published in the last 48 hours, lead with its recency ("Just dropped:", "This week:", "Released yesterday:") — freshness is a signal of credibility
- Do NOT use generic opener phrases like "In today's fast-paced world..." or "I'm excited to share..."
- Do NOT frame posts as "two stories" or narrative journalism
- Do NOT write about topics unrelated to AI (Go, Rust, Kubernetes, etc.) unless directly AI-adjacent
- Do NOT use excessive emojis — max 1–2 total, only if they add clarity

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

    # Add previously posted topics to avoid repetition
    posted_topics = load_posted_topics()
    avoid_section = ""
    if posted_topics:
        topics_list = "\n".join(f"- {t}" for t in posted_topics[-5:])
        avoid_section = f"""## Recently Posted Topics (DO NOT repeat these)
{topics_list}

Pick a distinctly different angle or topic from the news sources above.

"""

    user_message = f"""Please write a LinkedIn newsletter post based on the following context.

{video_section}

{news_section}

{avoid_section}{feedback_section}Create an AI-focused post that:
1. Opens with a specific, concrete observation about an AI model, tool, behaviour, or tradeoff
2. Delivers one clear insight relevant to engineers and builders working with AI
3. Connects the AI content to a practical implication — what should practitioners do differently?
4. Ends with a pointed question or takeaway for an AI-practitioner audience
5. If sources are not AI-specific, find the AI angle or ignore them and write from AI knowledge

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

    # Strip trailing hashtag lines from body — Claude embeds them there, but
    # they're also stored in draft["hashtags"], so appending both would duplicate.
    body_lines = draft.get("body", "").rstrip().split("\n")
    while body_lines and all(w.startswith("#") for w in body_lines[-1].split() if w):
        body_lines.pop()
    draft["body"] = "\n".join(body_lines).rstrip()

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

    # Generate expanded blog article for Medium + Dev.to
    try:
        from tools.generate_blog import generate_blog
        print("Generating blog article...", file=sys.stderr)
        draft["blog"] = generate_blog(draft)
        print(f"Blog generated: {draft['blog'].get('title', '')}", file=sys.stderr)
    except Exception as e:
        print(f"WARNING: Blog generation failed (LinkedIn draft unaffected): {e}", file=sys.stderr)

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
