#!/usr/bin/env python3
"""
Backfill existing Dev.to articles with content-specific images.

For each published article, Claude decides whether a Mermaid diagram or a
targeted photo best represents it, generates the image, commits it to the
repo, then updates the Dev.to article's cover image.

Usage:
    # Preview what would happen (no writes)
    python tools/backfill_devto_images.py --dry-run

    # Process first 5 articles only
    python tools/backfill_devto_images.py --limit 5

    # Re-generate even for articles that already have a cover image
    python tools/backfill_devto_images.py --force

    # Full backfill
    python tools/backfill_devto_images.py
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path so `tools.*` imports resolve regardless
# of how this script is invoked (python3 tools/backfill_devto_images.py)
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from dotenv import load_dotenv

load_dotenv()

DEVTO_API = "https://dev.to/api"


def fetch_my_articles(api_key: str, per_page: int = 30) -> list[dict]:
    """Fetch all published articles for the authenticated user."""
    articles = []
    page = 1
    while True:
        resp = httpx.get(
            f"{DEVTO_API}/articles/me/published",
            params={"per_page": per_page, "page": page},
            headers={"api-key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        articles.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return articles


def fetch_article_body(article_id: int, api_key: str) -> str:
    """Fetch the full body_markdown of a single article."""
    resp = httpx.get(
        f"{DEVTO_API}/articles/{article_id}",
        headers={"api-key": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("body_markdown", "")


def update_article_cover(article_id: int, image_url: str, api_key: str) -> None:
    """Update the cover image of a Dev.to article."""
    resp = httpx.put(
        f"{DEVTO_API}/articles/{article_id}",
        json={"article": {"main_image": image_url}},
        headers={"api-key": api_key, "Content-Type": "application/json"},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Dev.to update failed {resp.status_code}: {resp.text[:200]}")


def git_commit_and_push(paths: list[str], message: str) -> bool:
    """Stage, commit, and push the given paths. Returns True on success."""
    try:
        subprocess.run(["git", "add"] + paths, check=True)
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            if "nothing to commit" in result.stdout + result.stderr:
                print("Nothing new to commit.", file=sys.stderr)
                return True
            print(f"git commit failed: {result.stderr}", file=sys.stderr)
            return False
        subprocess.run(["git", "push"], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"git error: {e}", file=sys.stderr)
        return False


def get_repo_name() -> str:
    """Get the GitHub repo slug (owner/repo) from git remote."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True
        )
        url = result.stdout.strip()
        # Handle both SSH and HTTPS remotes
        if url.startswith("git@"):
            # git@github.com:owner/repo.git
            slug = url.split(":", 1)[1].removesuffix(".git")
        else:
            # https://github.com/owner/repo.git
            slug = url.split("github.com/", 1)[1].removesuffix(".git")
        return slug
    except Exception:
        return os.getenv("GITHUB_REPOSITORY", "owner/repo")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill Dev.to articles with content-specific images"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen — no files written, no API updates"
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Process at most N articles (0 = all)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-generate even if article already has a cover image"
    )
    args = parser.parse_args()

    api_key = os.getenv("DEVTO_API_KEY", "")
    if not api_key:
        print("ERROR: DEVTO_API_KEY is not set in .env", file=sys.stderr)
        sys.exit(1)

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        print("ERROR: ANTHROPIC_API_KEY is not set in .env", file=sys.stderr)
        sys.exit(1)

    # Lazy import — only needed at runtime, not for --help
    from tools.generate_smart_image import generate_smart_image

    print("Fetching your Dev.to articles...", file=sys.stderr)
    articles = fetch_my_articles(api_key)
    print(f"Found {len(articles)} published articles", file=sys.stderr)

    if args.limit:
        articles = articles[: args.limit]
        print(f"Processing first {args.limit} articles", file=sys.stderr)

    repo = get_repo_name()
    generated_paths: list[str] = []
    updates: list[dict] = []  # {"article_id": ..., "image_url": ..., "title": ...}
    skipped = 0

    for article in articles:
        article_id = article["id"]
        title = article.get("title", "")
        existing_cover = article.get("cover_image") or article.get("social_image") or ""

        if existing_cover and not args.force:
            print(f"  SKIP  [{article_id}] {title!r} (already has cover image)", file=sys.stderr)
            skipped += 1
            continue

        print(f"\n  Processing [{article_id}] {title!r}", file=sys.stderr)
        output_path = f"assets/covers/{article_id}.png"

        if args.dry_run:
            print(f"    DRY RUN: would generate image → {output_path}", file=sys.stderr)
            image_url = f"https://raw.githubusercontent.com/{repo}/main/assets/covers/{article_id}.png"
            updates.append({"article_id": article_id, "title": title, "image_url": image_url})
            continue

        # Fetch full body for better image decisions
        try:
            body = fetch_article_body(article_id, api_key)
        except Exception as e:
            print(f"    WARNING: could not fetch body ({e}), using title only", file=sys.stderr)
            body = ""

        try:
            generate_smart_image(
                title=title,
                blog_body=body,
                hook=article.get("description", ""),
                output_path=output_path,
            )
            generated_paths.append(output_path)
            image_url = f"https://raw.githubusercontent.com/{repo}/main/{output_path}"
            updates.append({"article_id": article_id, "title": title, "image_url": image_url})
        except Exception as e:
            print(f"    ERROR generating image: {e}", file=sys.stderr)

        # Rate limit: be polite to both Anthropic and Kroki.io
        time.sleep(2)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Generated: {len(generated_paths)} images", file=sys.stderr)
    print(f"Skipped:   {skipped} (already had cover image)", file=sys.stderr)
    if args.dry_run:
        print(f"\nDRY RUN — nothing was written. Would update {len(updates)} articles:", file=sys.stderr)
        for u in updates:
            print(f"  [{u['article_id']}] {u['title']!r}", file=sys.stderr)
        return

    if not generated_paths:
        print("No new images generated — nothing to commit.", file=sys.stderr)
        return

    # Commit all generated images first
    print(f"\nCommitting {len(generated_paths)} images to repo...", file=sys.stderr)
    commit_msg = f"chore: backfill Dev.to cover images ({len(generated_paths)} articles) [skip ci]"
    if not git_commit_and_push(generated_paths, commit_msg):
        print("ERROR: git commit/push failed — aborting Dev.to updates (images not publicly accessible yet)", file=sys.stderr)
        sys.exit(1)

    # Give GitHub a moment to make the raw URLs live
    print("Waiting 10s for GitHub CDN to serve new images...", file=sys.stderr)
    time.sleep(10)

    # Update Dev.to articles
    success = 0
    for u in updates:
        try:
            update_article_cover(u["article_id"], u["image_url"], api_key)
            print(f"  UPDATED [{u['article_id']}] {u['title']!r}", file=sys.stderr)
            success += 1
        except Exception as e:
            print(f"  ERROR updating [{u['article_id']}] {u['title']!r}: {e}", file=sys.stderr)
        time.sleep(1)  # polite rate limiting

    print(f"\nDone. Updated {success}/{len(updates)} Dev.to articles.", file=sys.stderr)


if __name__ == "__main__":
    main()
