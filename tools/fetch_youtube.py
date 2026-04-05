#!/usr/bin/env python3
"""
Fetch latest YouTube videos from a channel via RSS feed.
No API key required — uses YouTube's public RSS endpoint.

Usage:
    python tools/fetch_youtube.py
    python tools/fetch_youtube.py --channel-id UCxxxxxxxxx --max 3
    python tools/fetch_youtube.py --video-url https://youtu.be/xxxxx
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_RSS_BASE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
YOUTUBE_OEMBED_URL = "https://www.youtube.com/oembed?url={url}&format=json"


def channel_rss_url(channel_id: str) -> str:
    return YOUTUBE_RSS_BASE.format(channel_id=channel_id)


def extract_video_id(url: str) -> str | None:
    """Extract video ID from various YouTube URL formats."""
    import re

    patterns = [
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})",
        r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/embed/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    # bare ID
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", url.strip()):
        return url.strip()
    return None


def fetch_video_metadata(video_url: str) -> dict:
    """Fetch metadata for a specific video via oEmbed (no API key needed)."""
    oembed_url = YOUTUBE_OEMBED_URL.format(url=video_url)
    resp = httpx.get(oembed_url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    video_id = extract_video_id(video_url)
    return {
        "id": video_id,
        "title": data.get("title", ""),
        "channel": data.get("author_name", ""),
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "thumbnail": data.get("thumbnail_url", ""),
        "description": "",  # oEmbed doesn't include description
        "published": datetime.now(timezone.utc).isoformat(),
    }


def fetch_latest_videos(channel_id: str, max_videos: int = 5) -> list[dict]:
    """Fetch the latest videos from a YouTube channel via RSS."""
    rss_url = channel_rss_url(channel_id)
    feed = feedparser.parse(rss_url)

    if feed.bozo and not feed.entries:
        raise RuntimeError(f"Failed to parse RSS feed for channel {channel_id}: {feed.bozo_exception}")

    videos = []
    for entry in feed.entries[:max_videos]:
        video_id = entry.get("yt_videoid", "")
        published_raw = entry.get("published", "")
        try:
            published = datetime.fromisoformat(published_raw.replace("Z", "+00:00")).isoformat()
        except (ValueError, AttributeError):
            published = published_raw

        videos.append({
            "id": video_id,
            "title": entry.get("title", ""),
            "channel": feed.feed.get("title", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "description": entry.get("summary", ""),
            "published": published,
            "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        })

    return videos


def main():
    parser = argparse.ArgumentParser(description="Fetch YouTube video metadata")
    parser.add_argument("--channel-id", default=os.getenv("YOUTUBE_CHANNEL_ID"))
    parser.add_argument("--max", type=int, default=5, dest="max_videos")
    parser.add_argument("--video-url", help="Fetch metadata for a specific video URL")
    parser.add_argument("--output", help="Save JSON output to this file")
    args = parser.parse_args()

    try:
        if args.video_url:
            result = fetch_video_metadata(args.video_url)
            videos = [result]
        elif args.channel_id:
            videos = fetch_latest_videos(args.channel_id, args.max_videos)
        else:
            print("ERROR: Provide --channel-id or --video-url (or set YOUTUBE_CHANNEL_ID in .env)", file=sys.stderr)
            sys.exit(1)

        output = json.dumps(videos, indent=2)
        print(output)

        if args.output:
            Path(args.output).write_text(output)
            print(f"\nSaved to {args.output}", file=sys.stderr)

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
