#!/usr/bin/env python3
"""
Publish an approved draft as a LinkedIn post using the REST Posts API.

Uses POST /rest/posts — the standard LinkedIn API for member posts.
The post appears in the member's feed and is visible to connections/followers.

Note: LinkedIn's newsletter article API (/rest/articles) requires Marketing
Developer Platform partner access (business application required). This tool
uses the standard Posts API which works with any approved w_member_social token.

API docs: https://learn.microsoft.com/en-us/linkedin/marketing/integrations/community-management/shares/posts-api

Requirements:
  - Access token with scope: w_member_social
  - LinkedIn-Version header: 202501

Usage:
    python tools/post_linkedin.py --draft-file .tmp/pending_posts/abc123.json
    python tools/post_linkedin.py --body "Post text" --title "Headline"
    python tools/post_linkedin.py --draft-file abc123.json --dry-run
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

LINKEDIN_POSTS_URL    = "https://api.linkedin.com/rest/posts"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

# LinkedIn REST API version — bump this if LinkedIn rejects the request
LINKEDIN_VERSION = "202501"


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_person_urn(access_token: str) -> str:
    """Resolve the authenticated user's Person URN via the userinfo endpoint."""
    resp = httpx.get(
        LINKEDIN_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    sub = data.get("sub", "")           # may be "urn:li:person:XXXX" or just the ID
    if sub and not sub.startswith("urn:"):
        return f"urn:li:person:{sub}"
    return sub


def plain_text_to_html(text: str) -> str:
    """
    Convert plain-text LinkedIn post body to simple HTML for the Articles API.

    Rules:
    - Blank lines → new <p> paragraph
    - Single newlines within a paragraph → <br>
    - Hashtags on their own line → kept as-is inside a <p>
    - Bold markdown (**word**) → <strong>word</strong>
    """
    # Bold markdown
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

    # Split into paragraphs on blank lines
    paragraphs = re.split(r"\n{2,}", text.strip())
    html_parts = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # Single newlines within a paragraph become <br>
        para = para.replace("\n", "<br>")
        html_parts.append(f"<p>{para}</p>")

    return "\n".join(html_parts)


def _api_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }


# ── Core posting function ──────────────────────────────────────────────────────

def publish_post(
    commentary: str,
    access_token: str,
    person_urn: str,
) -> dict:
    """
    Publish a text post to LinkedIn using the Posts API.

    The post appears in the author's feed and is visible to their connections
    and followers. This uses the standard REST Posts API which is available
    to all LinkedIn developers with the w_member_social scope.

    Note: LinkedIn's newsletter article API (/rest/articles) requires
    Marketing Developer Platform partner access and is not available to
    standard developer apps. This posts to the member's feed instead.

    Returns a dict with the post ID and URL.
    """
    payload = {
        "author": person_urn,
        "commentary": commentary,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    resp = httpx.post(
        LINKEDIN_POSTS_URL,
        json=payload,
        headers=_api_headers(access_token),
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        _raise_linkedin_error(resp, payload)

    # Post ID is returned in x-restli-id header
    post_urn = resp.headers.get("x-restli-id", "")
    post_id = post_urn.split(":")[-1] if post_urn else ""

    return {
        "post_urn": post_urn,
        "status": "published",
        "url": (
            f"https://www.linkedin.com/feed/update/{post_urn}/"
            if post_urn else ""
        ),
    }


def _raise_linkedin_error(resp: httpx.Response, payload: dict) -> None:
    """Raise a descriptive error for failed LinkedIn API calls."""
    hints = ""
    if resp.status_code == 401:
        hints = "\nHint: Access token is expired or invalid. Refresh it at linkedin.com/developers."
    elif resp.status_code == 403:
        hints = (
            "\nHint: Your token may be missing the 'w_member_social' scope, "
            "or you are not the owner of this newsletter."
        )
    elif resp.status_code == 422:
        hints = (
            "\nHint: The request was rejected. Check that commentary is not empty "
            "and that the author URN is correct."
        )
    raise RuntimeError(
        f"LinkedIn API returned {resp.status_code}: {resp.text}{hints}\n"
        f"Payload sent: {json.dumps(payload, indent=2)}"
    )


# ── Public interface ───────────────────────────────────────────────────────────

def post_draft(draft: dict) -> dict:
    """Publish an approved draft dict as a LinkedIn post."""
    access_token = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    person_urn   = os.getenv("LINKEDIN_PERSON_URN", "")

    if not access_token:
        raise ValueError("LINKEDIN_ACCESS_TOKEN is not set in .env")

    if not person_urn:
        print("Resolving LinkedIn person URN...", file=sys.stderr)
        person_urn = get_person_urn(access_token)
        if not person_urn:
            raise ValueError(
                "Could not resolve your LinkedIn person URN. "
                "Set LINKEDIN_PERSON_URN in .env (format: urn:li:person:XXXXXXXX)"
            )

    body_text = draft.get("body", "")

    # Append hashtags to end of body
    hashtags = draft.get("hashtags", [])
    if hashtags:
        tag_line = " ".join(f"#{t.lstrip('#')}" for t in hashtags)
        if tag_line not in body_text:
            body_text = f"{body_text}\n\n{tag_line}"

    return publish_post(body_text, access_token, person_urn)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Publish an approved draft as a LinkedIn newsletter article"
    )
    parser.add_argument("--draft-file", help="Path to approved draft JSON file")
    parser.add_argument("--body",  help="Post body text (plain text, alternative to --draft-file)")
    parser.add_argument("--title", default="", help="Article title")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the payload that would be sent, without actually posting",
    )
    args = parser.parse_args()

    if args.draft_file:
        draft = json.loads(Path(args.draft_file).read_text())
    elif args.body:
        draft = {"body": args.body, "title": args.title, "hashtags": []}
    else:
        print("ERROR: Provide --draft-file or --body", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        body_text = draft.get("body", "")
        hashtags = draft.get("hashtags", [])
        if hashtags:
            tag_line = " ".join(f"#{t.lstrip('#')}" for t in hashtags)
            if tag_line not in body_text:
                body_text = f"{body_text}\n\n{tag_line}"
        print("DRY RUN — payload that would be sent to LinkedIn Posts API:")
        print(json.dumps({
            "author": os.getenv("LINKEDIN_PERSON_URN", "<urn:li:person:...>"),
            "commentary": body_text,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED"},
            "lifecycleState": "PUBLISHED",
        }, indent=2))
        sys.exit(0)

    try:
        result = post_draft(draft)
        print(json.dumps(result, indent=2))
        url = result.get("article_url") or result.get("newsletter_url", "")
        print(f"\nPublished to newsletter: {url}", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
