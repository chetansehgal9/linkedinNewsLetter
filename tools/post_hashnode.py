#!/usr/bin/env python3
"""
Publish a blog article to Hashnode using their GraphQL API.

Get your token: hashnode.com → Account Settings → Developer → Personal Access Tokens

You also need your Publication ID:
  - Go to your Hashnode blog dashboard
  - Settings → General → scroll down to find the Publication ID
  - Or: hashnode.com/@yourhandle — the ID is in the URL of your dashboard

Usage:
    python tools/post_hashnode.py --draft-file .tmp/draft.json
    python tools/post_hashnode.py --draft-file .tmp/draft.json --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

HASHNODE_API_URL = "https://gql.hashnode.com"

PUBLISH_MUTATION = """
mutation PublishPost($input: PublishPostInput!) {
  publishPost(input: $input) {
    post {
      id
      slug
      url
      title
    }
  }
}
"""


def publish_to_hashnode(
    title: str,
    body_markdown: str,
    tags: list[str],
    token: str,
    publication_id: str,
    canonical_url: str = "",
) -> dict:
    """Publish a Markdown article to Hashnode. Returns post URL and ID."""

    # Hashnode tags must be objects with {name, slug}
    tag_objects = [{"name": t, "slug": t.lower().replace(" ", "-")} for t in tags[:5]]

    variables = {
        "input": {
            "title": title,
            "contentMarkdown": body_markdown,
            "publicationId": publication_id,
            "tags": tag_objects,
        }
    }
    if canonical_url:
        variables["input"]["originalArticleURL"] = canonical_url

    resp = httpx.post(
        HASHNODE_API_URL,
        json={"query": PUBLISH_MUTATION, "variables": variables},
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Hashnode API failed {resp.status_code}: {resp.text}")

    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Hashnode GraphQL error: {data['errors']}")

    post = data["data"]["publishPost"]["post"]
    return {
        "platform": "hashnode",
        "post_id": post.get("id", ""),
        "url": post.get("url", ""),
        "status": "published",
    }


def post_blog_to_hashnode(draft: dict) -> dict:
    token = os.getenv("HASHNODE_TOKEN", "")
    publication_id = os.getenv("HASHNODE_PUBLICATION_ID", "")

    if not token:
        raise ValueError("HASHNODE_TOKEN is not set")
    if not publication_id:
        raise ValueError("HASHNODE_PUBLICATION_ID is not set")

    blog = draft.get("blog", {})
    if not blog:
        raise ValueError("Draft has no 'blog' key — run generate_blog first")

    return publish_to_hashnode(
        title=blog.get("title", draft.get("title", "")),
        body_markdown=blog.get("body", ""),
        tags=blog.get("tags", ["ai"]),
        token=token,
        publication_id=publication_id,
        canonical_url=blog.get("canonical_url", ""),
    )


def main():
    parser = argparse.ArgumentParser(description="Publish blog to Hashnode")
    parser.add_argument("--draft-file", required=True, help="Path to draft JSON")
    parser.add_argument("--dry-run", action="store_true", help="Print payload, don't post")
    args = parser.parse_args()

    draft = json.loads(Path(args.draft_file).read_text())
    blog = draft.get("blog", {})

    if not blog:
        print("ERROR: Draft has no 'blog' key", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("DRY RUN — payload that would be sent to Hashnode:")
        print(json.dumps({
            "title": blog.get("title", ""),
            "contentMarkdown": blog.get("body", "")[:200] + "...",
            "tags": blog.get("tags", []),
            "publicationId": os.getenv("HASHNODE_PUBLICATION_ID", "<your-publication-id>"),
        }, indent=2))
        sys.exit(0)

    try:
        result = post_blog_to_hashnode(draft)
        print(json.dumps(result, indent=2))
        print(f"\nPublished to Hashnode: {result.get('url', '')}", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
