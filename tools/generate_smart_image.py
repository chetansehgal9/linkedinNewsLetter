#!/usr/bin/env python3
"""
Generate a content-specific image for a blog post.

Claude analyzes the blog content and decides:
  - "diagram": generates Mermaid syntax, rendered to PNG via Kroki.io (free, no key)
  - "photo": generates a precise Unsplash search query for a relevant stock photo

Fallback chain: diagram render failure → photo → generic Unsplash fallback

Usage:
    python tools/generate_smart_image.py \
        --title "RAG Pipeline Optimization" \
        --blog-body "$(cat .tmp/blog.md)" \
        --output assets/drafts/preview.png

    python tools/generate_smart_image.py \
        --title "GPT-4o Mini Released" \
        --hook "OpenAI just shipped a smaller model" \
        --output .tmp/test.png
"""

import argparse
import json
import os
import sys
from pathlib import Path

import io
import textwrap

import anthropic
import httpx
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv()

KROKI_URL = "https://kroki.io/mermaid/png"

# Dev.to recommended cover image dimensions
COVER_W, COVER_H = 1000, 420
# Background colour for the canvas (dark slate — matches tech aesthetic)
CANVAS_BG     = (15, 23, 42)    # #0f172a
TITLE_COLOR   = (248, 250, 252) # #f8fafc — near-white
ACCENT_COLOR  = (99, 102, 241)  # #6366f1 — indigo accent line
# Title zone height (px); diagram fills the rest
TITLE_ZONE_H  = 90
# Horizontal padding for title text and diagram
H_PAD = 40
# Vertical padding inside the diagram zone
V_PAD = 16

# Candidate font paths (macOS + Linux/GitHub Actions)
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

DECISION_PROMPT = """You are deciding what visual best represents a blog post about AI.

Analyze the post below and return a JSON object specifying the most reader-attracting image.

## Decision rules

Choose **"diagram"** when the post explains:
- A process, pipeline, or multi-step flow (e.g. RAG, training loop, inference pipeline)
- A system architecture or component relationship
- A comparison or tradeoff between approaches
- A technical mechanism with discrete steps

Choose **"photo"** when the post is about:
- A model release, product announcement, or research paper result
- An industry trend, opinion, or prediction
- A concept better illustrated by a real-world analogy (e.g. "AI at the edge")

## Output format

Return ONLY valid JSON — no markdown, no explanation:

{
  "type": "diagram",
  "mermaid": "flowchart LR\\n  A[Input] --> B[Embed]\\n  B --> C[(Vector DB)]",
  "image_query": ""
}

OR

{
  "type": "photo",
  "mermaid": "",
  "image_query": "neural network chip close-up"
}

## Diagram rules (if type=diagram)
- ONLY use `flowchart LR` — left-to-right, landscape. NEVER use TD, graph TD, graph LR, or sequenceDiagram. No exceptions.
- Max 8 nodes arranged in a single horizontal flow (no tall branches, no deeply nested subgraphs)
- If branching is needed, keep it shallow: one branch level only (e.g. two parallel paths that reconnect)
- Labels ≤ 4 words each; node IDs are short (A, B, C…)
- Always start with: %%{init: {'theme': 'dark'}}%%
- Return the full Mermaid syntax in "mermaid"

## Photo rules (if type=photo)
- Be specific and visual — avoid generic terms like "artificial intelligence"
- Good: "robot arm sorting packages conveyor belt"
- Bad: "AI technology future"
- Return the search query in "image_query"
"""


def _call_claude(title: str, blog_body: str, hook: str) -> dict:
    """Ask Claude to decide diagram vs photo and generate the content."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Use a concise excerpt if body is very long
    body_excerpt = blog_body[:3000] if blog_body else ""

    user_message = f"""## Post Title
{title}

## Hook
{hook or "(none provided)"}

## Blog Body
{body_excerpt or "(none provided)"}

Decide the best visual and generate it. Return JSON only."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=DECISION_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    text = next(
        (block.text for block in response.content if block.type == "text"), ""
    ).strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(l for l in lines if not l.strip().startswith("```"))

    return json.loads(text)


def _render_mermaid(mermaid_code: str, output_path: str, title: str = "") -> str:
    """
    Render Mermaid diagram to PNG via Kroki.io, then composite onto a 1000×420 canvas.

    Layout (when title is provided):
      ┌──────────────────────────────────────┐
      │  Title text (90px, white)            │
      │──────────────────────────────────────│  ← 2px indigo accent line
      │                                      │
      │   Diagram scaled to fill this zone   │  ← remaining 328px
      │                                      │
      └──────────────────────────────────────┘
    """
    print("Rendering Mermaid diagram via Kroki.io...", file=sys.stderr)
    resp = httpx.post(
        KROKI_URL,
        content=mermaid_code.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
        timeout=30,
    )
    resp.raise_for_status()

    canvas = Image.new("RGB", (COVER_W, COVER_H), CANVAS_BG)
    draw = ImageDraw.Draw(canvas)

    # ── Title zone ──────────────────────────────────────────────────────────
    diagram_top = 0
    if title:
        font_size = 28
        font = _load_font(font_size)

        # Word-wrap the title to fit within H_PAD margins
        max_chars = max(20, (COVER_W - H_PAD * 2) // (font_size // 2))
        lines = textwrap.wrap(title, width=max_chars)[:2]  # max 2 lines

        line_h = font_size + 6
        text_block_h = len(lines) * line_h
        text_y = (TITLE_ZONE_H - text_block_h) // 2

        for line in lines:
            draw.text((H_PAD, text_y), line, font=font, fill=TITLE_COLOR)
            text_y += line_h

        # Accent separator line
        sep_y = TITLE_ZONE_H
        draw.rectangle([(0, sep_y), (COVER_W, sep_y + 2)], fill=ACCENT_COLOR)
        diagram_top = TITLE_ZONE_H + 2

    # ── Diagram zone ─────────────────────────────────────────────────────────
    diagram = Image.open(io.BytesIO(resp.content)).convert("RGBA")

    diagram_zone_h = COVER_H - diagram_top
    max_w = COVER_W - H_PAD * 2
    max_h = diagram_zone_h - V_PAD * 2

    # Scale to fill the available zone (allow upscaling)
    scale = min(max_w / diagram.width, max_h / diagram.height)
    new_w = max(1, int(diagram.width * scale))
    new_h = max(1, int(diagram.height * scale))
    diagram = diagram.resize((new_w, new_h), Image.LANCZOS)

    x = (COVER_W - new_w) // 2
    y = diagram_top + (diagram_zone_h - new_h) // 2
    canvas.paste(diagram, (x, y), mask=diagram)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    size_kb = Path(output_path).stat().st_size // 1024
    print(f"Diagram saved to {output_path} ({COVER_W}×{COVER_H}px, {size_kb} KB)", file=sys.stderr)
    return output_path


def _fetch_unsplash(query: str, output_path: str) -> str:
    """Fetch a photo from Unsplash using the given query. Returns output path."""
    access_key = os.getenv("UNSPLASH_ACCESS_KEY", "")
    if not access_key:
        raise ValueError("UNSPLASH_ACCESS_KEY is not set — cannot fall back to photo")

    print(f"Fetching Unsplash photo for: {query!r}", file=sys.stderr)
    resp = httpx.get(
        "https://api.unsplash.com/photos/random",
        params={
            "query": query,
            "orientation": "landscape",
            "content_filter": "high",
            "client_id": access_key,
        },
        timeout=15,
    )

    if resp.status_code == 404:
        # Retry with a simpler fallback query
        resp = httpx.get(
            "https://api.unsplash.com/photos/random",
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
    image_url = data["urls"]["regular"]
    photographer = data.get("user", {}).get("name", "Unknown")
    print(f"Photo by {photographer} on Unsplash", file=sys.stderr)

    img_resp = httpx.get(image_url, timeout=30, follow_redirects=True)
    img_resp.raise_for_status()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(img_resp.content)
    size_kb = len(img_resp.content) // 1024
    print(f"Photo saved to {output_path} ({size_kb} KB)", file=sys.stderr)
    return output_path


def generate_smart_image(
    title: str = "",
    blog_body: str = "",
    hook: str = "",
    output_path: str = ".tmp/post_image.png",
) -> str:
    """
    Generate the best content-specific image for a post.

    Returns the local file path of the generated image.
    Raises RuntimeError if all methods fail.
    """
    if not title and not blog_body:
        raise ValueError("Provide at least --title or --blog-body")

    # Step 1: Ask Claude what to generate
    print(f"Asking Claude to decide image type for: {title!r}", file=sys.stderr)
    decision = _call_claude(title, blog_body, hook)
    image_type = decision.get("type", "photo")
    print(f"Decision: {image_type}", file=sys.stderr)

    # Step 2: Execute the decision
    if image_type == "diagram":
        mermaid_code = decision.get("mermaid", "").strip()
        if not mermaid_code:
            print("WARNING: Claude chose diagram but returned empty Mermaid code — falling back to photo", file=sys.stderr)
        else:
            try:
                return _render_mermaid(mermaid_code, output_path, title=title)
            except Exception as e:
                print(f"WARNING: Mermaid render failed ({e}) — falling back to photo", file=sys.stderr)

    # Photo path (either chosen by Claude or fallback from failed diagram)
    image_query = decision.get("image_query", "").strip()
    if not image_query:
        # Build a basic query from the title if Claude didn't provide one
        image_query = title or "artificial intelligence technology"

    return _fetch_unsplash(image_query, output_path)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a content-specific image (diagram or photo) for a blog post"
    )
    parser.add_argument("--title", default="", help="Post title")
    parser.add_argument("--blog-body", default="", help="Full blog body (Markdown)")
    parser.add_argument("--hook", default="", help="Post hook / first sentence")
    parser.add_argument("--output", default=".tmp/post_image.png", help="Output file path (.png)")
    args = parser.parse_args()

    if not args.title and not args.blog_body:
        print("ERROR: Provide at least --title or --blog-body", file=sys.stderr)
        sys.exit(1)

    try:
        path = generate_smart_image(
            title=args.title,
            blog_body=args.blog_body,
            hook=args.hook,
            output_path=args.output,
        )
        print(path)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
