#!/usr/bin/env python3
"""
Publish a blog article to Dev.to using their Forem API.

Get your API key: dev.to → Settings → Extensions → DEV API Keys → Generate

Usage:
    python tools/post_devto.py --draft-file .tmp/draft.json
    python tools/post_devto.py --draft-file .tmp/draft.json --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

DEVTO_API_URL = "https://dev.to/api/articles"


def publish_to_devto(
    title: str,
    body_markdown: str,
    tags: list[str],
    api_key: str,
    canonical_url: str = "",
    cover_image_url: str = "",
) -> dict:
    """Publish a Markdown article to Dev.to. Returns post URL and ID."""
    article = {
        "title": title,
        "body_markdown": body_markdown,
        "published": True,
        "tags": tags[:4],  # Dev.to allows max 4 tags
    }
    if canonical_url:
        article["canonical_url"] = canonical_url
    if cover_image_url:
        article["main_image"] = cover_image_url

    resp = httpx.post(
        DEVTO_API_URL,
        json={"article": article},
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Dev.to publish failed {resp.status_code}: {resp.text}")

    data = resp.json()
    return {
        "platform": "devto",
        "post_id": str(data.get("id", "")),
        "url": data.get("url", ""),
        "status": "published",
    }


def post_blog_to_devto(draft: dict, cover_image_url: str = "") -> dict:
    api_key = os.getenv("DEVTO_API_KEY", "")
    if not api_key:
        raise ValueError("DEVTO_API_KEY is not set")

    blog = draft.get("blog", {})
    if not blog:
        raise ValueError("Draft has no 'blog' key — run generate_blog first")

    return publish_to_devto(
        title=blog.get("title", draft.get("title", "")),
        body_markdown=blog.get("body", ""),
        tags=blog.get("tags", ["ai"]),
        api_key=api_key,
        canonical_url=blog.get("canonical_url", ""),
        cover_image_url=cover_image_url,
    )


def main():
    parser = argparse.ArgumentParser(description="Publish blog to Dev.to")
    parser.add_argument("--draft-file", required=True, help="Path to draft JSON")
    parser.add_argument("--cover-image-url", default="", help="Public URL of cover image")
    parser.add_argument("--dry-run", action="store_true", help="Print payload, don't post")
    args = parser.parse_args()

    draft = json.loads(Path(args.draft_file).read_text())
    blog = draft.get("blog", {})

    if not blog:
        print("ERROR: Draft has no 'blog' key", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("DRY RUN — payload that would be sent to Dev.to:")
        print(json.dumps({
            "article": {
                "title": blog.get("title", ""),
                "body_markdown": blog.get("body", "")[:200] + "...",
                "tags": blog.get("tags", []),
                "published": True,
            }
        }, indent=2))
        sys.exit(0)

    try:
        result = post_blog_to_devto(draft, cover_image_url=args.cover_image_url)
        print(json.dumps(result, indent=2))
        print(f"\nPublished to Dev.to: {result.get('url', '')}", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
