#!/usr/bin/env python3
"""
LinkedIn Post Generator Agent — Main Orchestrator

This is the WAT Layer 2 (Agent). It reads the workflow SOP, coordinates the tools,
and handles the full lifecycle: fetch → draft → notify → approve → post.

Usage:
    # Full run: fetch content, generate draft, notify for approval
    python agent.py --run

    # Manual run with a specific YouTube video URL
    python agent.py --run --video-url https://youtu.be/xxxxx

    # Approve and post a pending draft
    python agent.py --approve <post_id>

    # Reject a pending draft
    python agent.py --reject <post_id>

    # List all pending drafts
    python agent.py --list

    # Dry run (generates draft but does NOT notify or post)
    python agent.py --run --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add project root to path so tools/* can be imported directly
sys.path.insert(0, str(Path(__file__).parent))

from tools.fetch_youtube import fetch_latest_videos, fetch_video_metadata
from tools.fetch_news import fetch_all_news
from tools.generate_draft import generate_draft
from tools.post_linkedin import post_draft
from tools.notify import notify, load_pending, mark_processed, list_pending


def run_pipeline(
    video_urls: list[str] | None = None,
    topics: list[str] | None = None,
    dry_run: bool = False,
    output_file: str | None = None,
) -> str | None:
    """
    Full pipeline: fetch content → generate draft → notify for approval.
    Returns post_id of the queued draft, or None on failure.
    """
    print("=" * 60)
    print("LinkedIn Post Generator Agent")
    print("=" * 60)

    # ── Step 1: Fetch YouTube videos ────────────────────────────────────────
    videos = []
    if video_urls:
        print(f"\n[1/3] Fetching metadata for {len(video_urls)} video(s)...")
        for url in video_urls:
            try:
                video = fetch_video_metadata(url)
                videos.append(video)
                print(f"      ✓ {video['title']}")
            except Exception as e:
                print(f"      ✗ Failed to fetch {url}: {e}")
    else:
        channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "")
        if channel_id:
            print(f"\n[1/3] Fetching latest videos from channel {channel_id}...")
            try:
                videos = fetch_latest_videos(channel_id, max_videos=2)
                for v in videos:
                    print(f"      ✓ {v['title']}")
            except Exception as e:
                print(f"      ✗ Failed to fetch channel videos: {e}")
        else:
            print("\n[1/3] No YouTube source configured — skipping video fetch")

    # ── Step 2: Fetch news ─────────────────────────────────────────────────
    print(f"\n[2/3] Fetching latest news...")
    feed_urls_raw = os.getenv("NEWS_RSS_FEEDS", "")
    feed_urls = [u.strip() for u in feed_urls_raw.split(",") if u.strip()]
    if not feed_urls:
        from tools.fetch_news import DEFAULT_FEEDS
        feed_urls = DEFAULT_FEEDS

    news_items = []
    try:
        news_items = fetch_all_news(feed_urls, max_per_feed=5, topics=topics)
        print(f"      ✓ Fetched {len(news_items)} articles")
    except Exception as e:
        print(f"      ✗ News fetch failed: {e}")

    if not videos and not news_items:
        print("\nERROR: No content to generate a post from. Aborting.")
        return None

    # ── Step 3: Generate draft ─────────────────────────────────────────────
    print(f"\n[3/3] Generating LinkedIn post draft with Claude...")
    try:
        draft = generate_draft(videos, news_items)
        print(f"      ✓ Draft generated: {draft.get('title', 'Untitled')}")
        print(f"      ✓ Tokens used: {draft.get('usage', {}).get('input_tokens', '?')} in / "
              f"{draft.get('usage', {}).get('output_tokens', '?')} out")
    except Exception as e:
        print(f"      ✗ Draft generation failed: {e}")
        return None

    if dry_run:
        print("\n── DRY RUN — Draft (not queued) ──")
        print(json.dumps(draft, indent=2))
        return None

    # ── Step 4a: Save to file (GitHub Actions mode) ────────────────────────
    if output_file:
        from pathlib import Path
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text(json.dumps(draft, indent=2))
        print(f"\nDraft saved to {output_file}")
        print(f"Title: {draft.get('title', 'Untitled')}")
        return draft.get("title", "draft")

    # ── Step 4b: Queue for approval (local mode) ───────────────────────────
    post_id = notify(draft)
    return post_id


def approve_and_post(post_id: str) -> bool:
    """Load a pending draft by ID, post it to LinkedIn, and mark it processed."""
    draft = load_pending(post_id)
    if not draft:
        print(f"ERROR: No pending draft with ID '{post_id}'")
        print("Run `python agent.py --list` to see pending drafts.")
        return False

    print(f"\nApproving post: {draft.get('title', 'Untitled')}")
    print("Posting to LinkedIn newsletter...")

    try:
        result = post_draft(draft)
        mark_processed(post_id, "approved")
        print(f"\nPosted! {result.get('url') or result.get('newsletter_url', '')}")
        print(json.dumps(result, indent=2))
        return True
    except Exception as e:
        print(f"ERROR posting to LinkedIn: {e}")
        return False


def reject_draft(post_id: str) -> bool:
    """Reject a pending draft."""
    draft = load_pending(post_id)
    if not draft:
        print(f"ERROR: No pending draft with ID '{post_id}'")
        return False
    mark_processed(post_id, "rejected")
    print(f"Draft '{post_id}' rejected.")
    return True


def main():
    parser = argparse.ArgumentParser(description="LinkedIn Post Generator Agent")

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--run", action="store_true", help="Run full pipeline")
    action.add_argument("--approve", metavar="POST_ID", help="Approve and post a draft")
    action.add_argument("--reject", metavar="POST_ID", help="Reject a draft")
    action.add_argument("--list", action="store_true", help="List pending drafts")

    parser.add_argument("--video-url", action="append", dest="video_urls",
                        help="YouTube video URL(s) to feature (repeat for multiple)")
    parser.add_argument("--topics", help="Comma-separated news topics to filter")
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate draft but skip notification and posting")
    parser.add_argument("--output", metavar="FILE",
                        help="Save draft JSON to FILE instead of queuing (used by GitHub Actions)")

    args = parser.parse_args()

    if args.list:
        pending = list_pending()
        if not pending:
            print("No pending drafts.")
        else:
            print(f"\n{'ID':<10} {'Title':<45} Queued At")
            print("─" * 75)
            for d in pending:
                print(f"{d['post_id']:<10} {d.get('title', 'Untitled')[:44]:<45} {d.get('queued_at', '')[:19]}")
        return

    if args.approve:
        sys.exit(0 if approve_and_post(args.approve) else 1)

    if args.reject:
        sys.exit(0 if reject_draft(args.reject) else 1)

    if args.run:
        topics = [t.strip() for t in (args.topics or "").split(",") if t.strip()] or None
        post_id = run_pipeline(
            video_urls=args.video_urls,
            topics=topics,
            dry_run=args.dry_run,
            output_file=args.output,
        )
        if post_id:
            print(f"\nDraft queued with ID: {post_id}")
            print(f"Approve with: python agent.py --approve {post_id}")
        sys.exit(0 if (post_id or args.dry_run) else 1)


if __name__ == "__main__":
    main()
