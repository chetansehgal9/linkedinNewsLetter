#!/usr/bin/env python3
"""
Fetch latest news articles from RSS feeds.
No API key required — uses public RSS endpoints.

Usage:
    python tools/fetch_news.py
    python tools/fetch_news.py --feeds "https://feed1.com/rss,https://feed2.com/rss" --max 3
    python tools/fetch_news.py --topics "AI,machine learning" --output .tmp/news.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import httpx
from dotenv import load_dotenv

load_dotenv()

# Default feeds — override via NEWS_RSS_FEEDS env var or --feeds flag
# Focused on engineering, AI/ML, and developer tools — not consumer tech or startup news
DEFAULT_FEEDS = [
    "https://hnrss.org/frontpage",                           # Hacker News — engineering community
    "https://www.infoq.com/feed/",                           # InfoQ — software architecture, dev practices
    "https://github.blog/feed/",                             # GitHub Blog — open source, engineering
    "https://newsletter.pragmaticengineer.com/feed",         # The Pragmatic Engineer
    "https://tldr.tech/api/rss/tech",                        # TLDR Tech — curated dev news
]


def parse_date(entry: dict) -> str:
    """Parse date from feedparser entry, return ISO 8601 string."""
    for field in ("published", "updated", "created"):
        raw = entry.get(field)
        if raw:
            try:
                return parsedate_to_datetime(raw).isoformat()
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()


def fetch_feed(url: str, max_items: int = 5, topics: list[str] | None = None) -> list[dict]:
    """Fetch articles from a single RSS feed, optionally filtered by topics."""
    # Fetch raw XML via httpx first (feedparser's built-in fetcher can fail
    # due to SSL/User-Agent issues in some environments), then parse the content.
    try:
        resp = httpx.get(
            url,
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RSSReader/1.0)"},
        )
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception:
        # Fall back to feedparser's native fetch
        feed = feedparser.parse(url)

    articles = []
    for entry in feed.entries:
        title = entry.get("title", "")
        summary = entry.get("summary", entry.get("description", ""))
        link = entry.get("link", "")

        # Topic filter: skip if topics provided and none match title/summary
        if topics:
            text = (title + " " + summary).lower()
            if not any(t.lower() in text for t in topics):
                continue

        articles.append({
            "title": title,
            "summary": _clean_html(summary)[:500],  # truncate long summaries
            "url": link,
            "source": feed.feed.get("title", url),
            "published": parse_date(entry),
        })

        if len(articles) >= max_items:
            break

    return articles


def _clean_html(text: str) -> str:
    """Strip HTML tags from text."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


def fetch_all_news(
    feed_urls: list[str],
    max_per_feed: int = 5,
    topics: list[str] | None = None,
) -> list[dict]:
    """Fetch articles from all configured RSS feeds."""
    all_articles = []
    for url in feed_urls:
        try:
            articles = fetch_feed(url, max_per_feed, topics)
            all_articles.extend(articles)
        except Exception as e:
            print(f"WARNING: Failed to fetch {url}: {e}", file=sys.stderr)

    # Sort by published date, newest first
    all_articles.sort(key=lambda a: a.get("published", ""), reverse=True)
    return all_articles


def main():
    parser = argparse.ArgumentParser(description="Fetch latest news from RSS feeds")
    parser.add_argument(
        "--feeds",
        default=os.getenv("NEWS_RSS_FEEDS", ""),
        help="Comma-separated RSS feed URLs",
    )
    parser.add_argument("--max", type=int, default=int(os.getenv("NEWS_MAX_ITEMS", "5")))
    parser.add_argument("--topics", default="", help="Comma-separated topic keywords to filter")
    parser.add_argument("--output", help="Save JSON output to this file")
    args = parser.parse_args()

    feed_urls = [u.strip() for u in args.feeds.split(",") if u.strip()] or DEFAULT_FEEDS
    topics = [t.strip() for t in args.topics.split(",") if t.strip()] or None

    articles = fetch_all_news(feed_urls, args.max, topics)

    output = json.dumps(articles, indent=2)
    print(output)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output)
        print(f"\nSaved {len(articles)} articles to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
