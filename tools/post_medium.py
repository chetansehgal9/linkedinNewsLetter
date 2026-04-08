#!/usr/bin/env python3
"""
Publish a blog article to Medium using their Integration Token API.

Get your token: medium.com → Settings → Security → Integration tokens

Usage:
    python tools/post_medium.py --draft-file .tmp/draft.json
    python tools/post_medium.py --draft-file .tmp/draft.json --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

MEDIUM_API_BASE = "https://api.medium.com/v1"


def get_medium_user_id(token: str) -> str:
    resp = httpx.get(
        f"{MEDIUM_API_BASE}/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Medium /me failed {resp.status_code}: {resp.text}")
    return resp.json()["data"]["id"]


def publish_to_medium(
    title: str,
    body_markdown: str,
    tags: list[str],
    token: str,
    canonical_url: str = "",
) -> dict:
    """Publish a Markdown article to Medium. Returns post URL and ID."""
    user_id = get_medium_user_id(token)

    payload = {
        "title": title,
        "contentFormat": "markdown",
        "content": body_markdown,
        "tags": tags[:5],  # Medium allows max 5 tags
        "publishStatus": "public",
    }
    if canonical_url:
        payload["canonicalUrl"] = canonical_url

    resp = httpx.post(
        f"{MEDIUM_API_BASE}/users/{user_id}/posts",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Medium publish failed {resp.status_code}: {resp.text}")

    data = resp.json()["data"]
    return {
        "platform": "medium",
        "post_id": data.get("id", ""),
        "url": data.get("url", ""),
        "status": "published",
    }


def post_blog_to_medium(draft: dict) -> dict:
    token = os.getenv("MEDIUM_INTEGRATION_TOKEN", "")
    if not token:
        raise ValueError("MEDIUM_INTEGRATION_TOKEN is not set")

    blog = draft.get("blog", {})
    if not blog:
        raise ValueError("Draft has no 'blog' key — run generate_blog first")

    return publish_to_medium(
        title=blog.get("title", draft.get("title", "")),
        body_markdown=blog.get("body", ""),
        tags=blog.get("tags", ["ai"]),
        token=token,
        canonical_url=blog.get("canonical_url", ""),
    )


def main():
    parser = argparse.ArgumentParser(description="Publish blog to Medium")
    parser.add_argument("--draft-file", required=True, help="Path to draft JSON")
    parser.add_argument("--dry-run", action="store_true", help="Print payload, don't post")
    args = parser.parse_args()

    draft = json.loads(Path(args.draft_file).read_text())
    blog = draft.get("blog", {})

    if not blog:
        print("ERROR: Draft has no 'blog' key", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("DRY RUN — payload that would be sent to Medium:")
        print(json.dumps({
            "title": blog.get("title", ""),
            "contentFormat": "markdown",
            "content": blog.get("body", "")[:200] + "...",
            "tags": blog.get("tags", []),
            "publishStatus": "public",
        }, indent=2))
        sys.exit(0)

    try:
        result = post_blog_to_medium(draft)
        print(json.dumps(result, indent=2))
        print(f"\nPublished to Medium: {result.get('url', '')}", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
