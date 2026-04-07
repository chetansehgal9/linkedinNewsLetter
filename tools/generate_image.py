#!/usr/bin/env python3
"""
Fetch a relevant stock photo from Unsplash for a LinkedIn post.
Free tier: 50 requests/hour. No cost.

Sign up at https://unsplash.com/developers to get a free Access Key.

Usage:
    python tools/generate_image.py --title "On-Device AI" --output .tmp/image.jpg
    python tools/generate_image.py --hook "Gemma 4 runs locally" --output assets/drafts/preview.jpg
"""

import argparse
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

UNSPLASH_API = "https://api.unsplash.com/photos/random"

# Fallback search terms if nothing better can be derived
_FALLBACK_QUERIES = ["artificial intelligence", "machine learning", "technology"]

# Words to strip from the title/hook before searching — too generic for Unsplash
_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "are", "was", "were", "be", "been", "has", "have",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "just", "now", "new", "how", "why", "what", "when", "where", "who",
    "your", "my", "our", "their", "its", "this", "that", "these", "those",
    "not", "no", "so", "if", "as", "by", "up", "out", "get", "got",
}


def _build_query(title: str, hook: str) -> str:
    """Extract meaningful keywords from title/hook for the Unsplash search."""
    text = f"{title} {hook}".lower()
    # Strip punctuation
    text = re.sub(r"[^\w\s]", " ", text)
    words = [w for w in text.split() if w and w not in _STOP_WORDS and len(w) > 2]

    # Prefer specific AI/tech terms if present
    tech_terms = [
        w for w in words
        if any(kw in w for kw in ["ai", "llm", "gpt", "model", "neural", "agent",
                                   "robot", "data", "chip", "cloud", "code", "tech",
                                   "machine", "learn", "infer", "gemma", "claude",
                                   "device", "edge", "compute", "server", "gpu"])
    ]

    if tech_terms:
        query = " ".join(tech_terms[:3])
    elif words:
        query = " ".join(words[:4])
    else:
        query = _FALLBACK_QUERIES[0]

    # Always anchor to tech context
    if "technology" not in query and "tech" not in query:
        query = f"{query} technology"

    return query


def fetch_unsplash_image(
    title: str = "",
    hook: str = "",
    output_path: str = ".tmp/post_image.jpg",
) -> str:
    """
    Search Unsplash for a relevant photo and download it to output_path.
    Returns the local file path.
    """
    access_key = os.getenv("UNSPLASH_ACCESS_KEY", "")
    if not access_key:
        raise ValueError("UNSPLASH_ACCESS_KEY is not set in .env")

    query = _build_query(title, hook)
    print(f"Searching Unsplash for: {query!r}", file=sys.stderr)

    resp = httpx.get(
        UNSPLASH_API,
        params={
            "query": query,
            "orientation": "landscape",
            "content_filter": "high",
            "client_id": access_key,
        },
        timeout=15,
    )

    if resp.status_code == 403:
        raise RuntimeError("Unsplash API: invalid or missing access key")
    if resp.status_code == 404:
        # No results for specific query — fall back to generic tech photo
        print(f"No results for {query!r}, retrying with 'artificial intelligence technology'", file=sys.stderr)
        resp = httpx.get(
            UNSPLASH_API,
            params={
                "query": "artificial intelligence technology",
                "orientation": "landscape",
                "content_filter": "high",
                "client_id": access_key,
            },
            timeout=15,
        )
    resp.raise_for_status()

    data = resp.json()
    image_url = data["urls"]["regular"]  # ~1080px wide, good quality
    photographer = data.get("user", {}).get("name", "Unknown")
    print(f"Photo by {photographer} on Unsplash", file=sys.stderr)
    print(f"Image URL: {image_url}", file=sys.stderr)

    # Download image
    img_resp = httpx.get(image_url, timeout=30, follow_redirects=True)
    img_resp.raise_for_status()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(img_resp.content)
    print(f"Saved to {output_path} ({len(img_resp.content) // 1024} KB)", file=sys.stderr)

    return output_path


# Keep the same public interface as before
def generate_image(
    title: str = "",
    hook: str = "",
    output_path: str = ".tmp/post_image.jpg",
    **_kwargs,
) -> str:
    return fetch_unsplash_image(title, hook, output_path)


def main():
    parser = argparse.ArgumentParser(description="Fetch a LinkedIn post image from Unsplash")
    parser.add_argument("--title", default="", help="Post title")
    parser.add_argument("--hook", default="", help="Post hook / first sentence")
    parser.add_argument("--output", default=".tmp/post_image.jpg", help="Output file path")
    args = parser.parse_args()

    if not args.title and not args.hook:
        print("ERROR: Provide --title or --hook", file=sys.stderr)
        sys.exit(1)

    path = generate_image(args.title, args.hook, args.output)
    print(path)


if __name__ == "__main__":
    main()
