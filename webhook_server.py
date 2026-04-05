#!/usr/bin/env python3
"""
Webhook server — GitHub webhooks receiver + browser-based approval UI.

Endpoints:
  POST /webhook/github     — Receives GitHub push events, triggers the pipeline
  GET  /drafts             — Lists all pending drafts (HTML)
  GET  /drafts/{id}        — View a specific draft (HTML)
  POST /drafts/{id}/approve — Approve and post to LinkedIn
  POST /drafts/{id}/reject  — Reject a draft
  POST /drafts/{id}/edit    — Update the draft body before approving

Start the server:
  uvicorn webhook_server:app --host 0.0.0.0 --port 8000 --reload

For local GitHub webhooks use ngrok:
  ngrok http 8000
  → Set GitHub webhook URL to: https://xxxxx.ngrok.io/webhook/github
"""

import hashlib
import hmac
import json
import os
import re
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from agent import run_pipeline, approve_and_post, reject_draft
from tools.notify import load_pending, list_pending, PENDING_DIR, save_pending, verify_token, generate_token

app = FastAPI(title="LinkedIn Post Generator", docs_url=None)

WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")


# ── Helpers ────────────────────────────────────────────────────────────────────

def verify_github_signature(payload: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET:
        return True  # Skip verification if secret not configured
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def extract_youtube_urls(text: str) -> list[str]:
    """Extract all YouTube URLs from a string."""
    pattern = r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[a-zA-Z0-9_-]{11}"
    return re.findall(pattern, text)


def payload_to_video_urls(push_data: dict) -> list[str]:
    """Extract YouTube URLs from a GitHub push payload (commits + changed files)."""
    urls = []
    for commit in push_data.get("commits", []):
        msg = commit.get("message", "")
        urls.extend(extract_youtube_urls(msg))
    return list(dict.fromkeys(urls))  # deduplicate, preserve order


# ── GitHub Webhook ──────────────────────────────────────────────────────────────

@app.post("/webhook/github")
async def github_webhook(request: Request):
    payload_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_github_signature(payload_bytes, signature):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    event = request.headers.get("X-GitHub-Event", "")
    if event != "push":
        return JSONResponse({"status": "ignored", "event": event})

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    ref = payload.get("ref", "")
    default_branch = payload.get("repository", {}).get("default_branch", "main")
    if not ref.endswith(f"/{default_branch}"):
        return JSONResponse({"status": "ignored", "reason": f"not default branch ({ref})"})

    video_urls = payload_to_video_urls(payload)
    print(f"\nGitHub push received. Videos found: {video_urls or 'none'}")

    # Run pipeline in background (don't block the webhook response)
    import asyncio
    asyncio.create_task(_run_pipeline_async(video_urls or None))

    return JSONResponse({
        "status": "accepted",
        "videos_detected": len(video_urls),
        "message": "Pipeline started. Check /drafts for output."
    })


async def _run_pipeline_async(video_urls: list[str] | None):
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: run_pipeline(video_urls=video_urls))


# ── Approval UI ────────────────────────────────────────────────────────────────

def _base_html(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          max-width: 720px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; }}
  h1 {{ color: #0077b5; }} h2 {{ color: #333; }}
  .draft {{ background: #f9f9f9; border: 1px solid #ddd; border-radius: 8px;
            padding: 20px; white-space: pre-wrap; font-size: 15px; line-height: 1.6; }}
  .btn {{ display: inline-block; padding: 10px 22px; border-radius: 6px; border: none;
          cursor: pointer; font-size: 15px; font-weight: 600; text-decoration: none; }}
  .btn-approve {{ background: #0077b5; color: white; }}
  .btn-reject  {{ background: #cc0000; color: white; margin-left: 10px; }}
  .btn-back    {{ background: #eee; color: #333; margin-left: 10px; }}
  textarea {{ width: 100%; height: 280px; font-size: 14px; line-height: 1.5;
              padding: 12px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 6px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td, th {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #eee; }}
  th {{ background: #f5f5f5; font-weight: 600; }}
  a {{ color: #0077b5; }}
</style>
</head>
<body>
<h1>LinkedIn Post Generator</h1>
{body}
</body>
</html>"""


@app.get("/drafts", response_class=HTMLResponse)
async def list_drafts():
    pending = list_pending()
    if not pending:
        rows = "<tr><td colspan='3' style='color:#999'>No pending drafts</td></tr>"
    else:
        rows = ""
        for d in pending:
            pid = d["post_id"]
            title = d.get("title", "Untitled")
            queued = d.get("queued_at", "")[:19]
            rows += f"""<tr>
              <td><a href="/drafts/{pid}">{pid}</a></td>
              <td><a href="/drafts/{pid}">{title}</a></td>
              <td>{queued}</td>
            </tr>"""

    body = f"""
<h2>Pending Drafts ({len(pending)})</h2>
<table>
  <thead><tr><th>ID</th><th>Title</th><th>Queued At</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
<p style="margin-top:20px">
  <a href="/trigger" class="btn btn-approve">+ Trigger New Run</a>
</p>"""
    return _base_html("Pending Drafts", body)


@app.get("/drafts/{post_id}", response_class=HTMLResponse)
async def view_draft(post_id: str):
    draft = load_pending(post_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    title = draft.get("title", "Untitled")
    body_text = draft.get("body", "")
    hashtags = " ".join(f"#{t}" for t in draft.get("hashtags", []))
    full_text = body_text + (f"\n\n{hashtags}" if hashtags else "")

    sources = draft.get("sources", {})
    video_links = " | ".join(
        f"<a href='{v['url']}' target='_blank'>{v['title']}</a>"
        for v in sources.get("videos", [])
    )
    news_links = " | ".join(
        f"<a href='{n['url']}' target='_blank'>{n['title']}</a>"
        for n in sources.get("news", [])
    )

    body = f"""
<h2>{title}</h2>
{"<p class='meta'>Video: " + video_links + "</p>" if video_links else ""}
{"<p class='meta'>News: " + news_links + "</p>" if news_links else ""}

<form method="POST" action="/drafts/{post_id}/approve">
  <textarea name="body">{full_text}</textarea>
  <p>
    <button type="submit" class="btn btn-approve">✅ Approve &amp; Post to LinkedIn</button>
    <a href="/drafts/{post_id}/reject" class="btn btn-reject"
       onclick="return confirm('Reject this draft?')">❌ Reject</a>
    <a href="/drafts" class="btn btn-back">← Back</a>
  </p>
</form>"""
    return _base_html(f"Review: {title}", body)


@app.post("/drafts/{post_id}/approve", response_class=HTMLResponse)
async def approve_draft(post_id: str, request: Request, body: str = Form(default="")):
    token = request.query_params.get("token", "")
    # Allow no-token access only from localhost (browser UI usage)
    is_local = request.client.host in ("127.0.0.1", "::1", "localhost")
    if not is_local and not verify_token(post_id, "approve", token):
        raise HTTPException(status_code=403, detail="Invalid or missing approval token")

    draft = load_pending(post_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    # Update body if user edited it in the form
    if body:
        # Separate hashtags back out
        lines = body.strip().split("\n")
        hashtag_line = lines[-1] if lines and lines[-1].startswith("#") else ""
        post_body = body[: -len(hashtag_line)].strip() if hashtag_line else body.strip()
        draft["body"] = post_body
        if hashtag_line:
            draft["hashtags"] = [t.lstrip("#") for t in hashtag_line.split()]

    # Overwrite the pending file with the (possibly edited) draft
    path = PENDING_DIR / f"{post_id}.json"
    path.write_text(json.dumps(draft, indent=2))

    success = approve_and_post(post_id)
    if success:
        return HTMLResponse(_base_html(
            "Posted!",
            "<h2>✅ Post published to LinkedIn!</h2>"
            "<p><a href='/drafts' class='btn btn-approve'>← View Drafts</a></p>"
        ))
    else:
        return HTMLResponse(_base_html(
            "Error",
            "<h2>❌ Failed to post</h2>"
            "<p>Check the server logs for details.</p>"
            f"<p><a href='/drafts/{post_id}' class='btn btn-back'>← Back to Draft</a></p>"
        ), status_code=500)


@app.get("/drafts/{post_id}/reject", response_class=HTMLResponse)
async def reject_draft_endpoint(post_id: str, request: Request, token: str = ""):
    is_local = request.client.host in ("127.0.0.1", "::1", "localhost")
    if not is_local and not verify_token(post_id, "reject", token):
        raise HTTPException(status_code=403, detail="Invalid or missing rejection token")
    reject_draft(post_id)
    return HTMLResponse(_base_html(
        "Rejected",
        "<h2>Draft rejected.</h2>"
        "<p><a href='/drafts' class='btn btn-back'>← View Drafts</a></p>"
    ))


# ── Manual trigger UI ──────────────────────────────────────────────────────────

@app.get("/trigger", response_class=HTMLResponse)
async def trigger_form():
    body = """
<h2>Trigger New Post Generation</h2>
<form method="POST" action="/trigger">
  <p>
    <label><strong>YouTube Video URL (optional)</strong></label><br>
    <input type="url" name="video_url" placeholder="https://youtu.be/..." style="width:100%;padding:8px;box-sizing:border-box">
  </p>
  <p>
    <label><strong>News Topic Filter (optional)</strong></label><br>
    <input type="text" name="topics" placeholder="AI, developer tools, startups"
           style="width:100%;padding:8px;box-sizing:border-box">
  </p>
  <button type="submit" class="btn btn-approve">Generate Draft</button>
  <a href="/drafts" class="btn btn-back">← Back</a>
</form>"""
    return _base_html("Trigger New Run", body)


@app.post("/trigger", response_class=HTMLResponse)
async def trigger_run(
    video_url: str = Form(default=""),
    topics: str = Form(default=""),
):
    video_urls = [video_url.strip()] if video_url.strip() else None
    topic_list = [t.strip() for t in topics.split(",") if t.strip()] or None

    import asyncio
    asyncio.create_task(_run_pipeline_async_with_args(video_urls, topic_list))

    return HTMLResponse(_base_html(
        "Running...",
        "<h2>Pipeline started!</h2>"
        "<p>Draft will appear in <a href='/drafts'>Pending Drafts</a> shortly.</p>"
        "<p><a href='/drafts' class='btn btn-approve'>View Drafts</a></p>"
    ))


async def _run_pipeline_async_with_args(video_urls, topics):
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: run_pipeline(video_urls=video_urls, topics=topics))


# ── Health check ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse(url="/drafts")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("webhook_server:app", host="0.0.0.0", port=port, reload=True)
