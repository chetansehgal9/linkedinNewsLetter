#!/usr/bin/env python3
"""
Generate a LinkedIn post banner image using OpenAI DALL-E 3.
Downloads the generated image to a local temp file.

Usage:
    python tools/generate_image.py --hook "Claude 4 just shipped extended thinking" --output .tmp/image.png
    python tools/generate_image.py --title "On-Device AI" --hook "Gemma 4 runs locally" --output .tmp/image.png
"""

import argparse
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()


def build_image_prompt(title: str, hook: str) -> str:
    """Build a DALL-E 3 prompt for a LinkedIn post banner."""
    topic = hook or title
    return (
        f"A professional, modern LinkedIn article banner image for an AI/tech post about: {topic}. "
        "Style: clean, abstract, minimal — dark navy or deep blue background with glowing geometric "
        "shapes, neural network nodes, or circuit-like patterns in electric blue, cyan, and white. "
        "No text. No people. No logos. Suitable for a professional tech audience. "
        "Aspect ratio: landscape (wide). High quality."
    )


def generate_image(
    title: str = "",
    hook: str = "",
    output_path: str = ".tmp/post_image.png",
    size: str = "1792x1024",
) -> str:
    """
    Generate a DALL-E 3 image and save it to output_path.
    Returns the local file path.
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set in .env")

    client = OpenAI(api_key=api_key)
    prompt = build_image_prompt(title, hook)

    print(f"Generating image with DALL-E 3...", file=sys.stderr)
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size=size,
        quality="standard",
        n=1,
    )

    image_url = response.data[0].url
    print(f"Image URL: {image_url}", file=sys.stderr)

    # Download image to local file
    resp = httpx.get(image_url, timeout=60, follow_redirects=True)
    resp.raise_for_status()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(resp.content)
    print(f"Saved to {output_path} ({len(resp.content) // 1024} KB)", file=sys.stderr)

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate a LinkedIn post image via DALL-E 3")
    parser.add_argument("--title", default="", help="Post title")
    parser.add_argument("--hook", default="", help="Post hook / first sentence")
    parser.add_argument("--output", default=".tmp/post_image.png", help="Output file path")
    parser.add_argument("--size", default="1792x1024",
                        choices=["1024x1024", "1792x1024", "1024x1792"],
                        help="Image dimensions")
    args = parser.parse_args()

    if not args.title and not args.hook:
        print("ERROR: Provide --title or --hook", file=sys.stderr)
        sys.exit(1)

    path = generate_image(args.title, args.hook, args.output, args.size)
    print(path)


if __name__ == "__main__":
    main()
