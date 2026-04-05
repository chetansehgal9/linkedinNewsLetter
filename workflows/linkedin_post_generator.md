# Workflow: LinkedIn Post Generator

## Objective
Auto-draft LinkedIn newsletter posts by combining your latest YouTube videos with trending news in your space. You review and approve before anything goes live.

**Target publication:** https://www.linkedin.com/newsletters/7446074746422808576/

---

## Inputs Required

| Input | Source | Required |
|-------|--------|----------|
| YouTube channel ID | `YOUTUBE_CHANNEL_ID` env var | Optional — can provide video URL directly |
| News RSS feeds | `NEWS_RSS_FEEDS` env var | Optional — falls back to TechCrunch/Verge/HN |
| Writing style | `workflows/writing_style.md` | Highly recommended — fill this in |
| Claude API key | `ANTHROPIC_API_KEY` env var | Yes |
| LinkedIn access token | `LINKEDIN_ACCESS_TOKEN` env var | Yes (for posting) |

---

## Tools

| Step | Tool | Description |
|------|------|-------------|
| 1 | `tools/fetch_youtube.py` | Fetch latest video(s) from your channel or a specific URL |
| 2 | `tools/fetch_news.py` | Fetch latest articles from configured RSS feeds |
| 3 | `tools/generate_draft.py` | Call Claude API to draft a LinkedIn post |
| 4 | `tools/notify.py` | Save draft to `.tmp/pending_posts/` and notify you |
| 5 | `tools/post_linkedin.py` | Post approved draft to LinkedIn newsletter |

---

## Trigger Methods

### A. Manual run (quickest to start)
```bash
# Run the full pipeline
python agent.py --run

# Feature a specific YouTube video
python agent.py --run --video-url https://youtu.be/YOUR_VIDEO_ID

# With topic filtering for news
python agent.py --run --topics "AI, developer tools"

# Dry run (preview only, nothing saved or posted)
python agent.py --run --dry-run
```

### B. Web UI (browser-based approval)
```bash
# Start the server
uvicorn webhook_server:app --reload

# Open in browser
open http://localhost:8000

# Or use ngrok for external access
ngrok http 8000
```

### C. GitHub Webhook (fully automated trigger)
1. Start the server and expose it via ngrok or a VPS
2. Go to your GitHub repo → Settings → Webhooks → Add webhook
3. Set Payload URL to: `https://your-server.com/webhook/github`
4. Content type: `application/json`
5. Secret: same value as `GITHUB_WEBHOOK_SECRET` in `.env`
6. Trigger on: "Just the push event"

**Trigger convention:** When you push a commit that contains a YouTube URL in the commit message, the agent auto-detects it and generates a draft.

```bash
# Example commit message that auto-triggers with a specific video
git commit -m "New video: https://youtu.be/YOUR_VIDEO_ID — cover ML pipelines topic"
git push
```

---

## Approval Flow

After the pipeline runs, a draft is saved to `.tmp/pending_posts/{post_id}.json`.

**Option 1 — CLI:**
```bash
python agent.py --list                    # see pending drafts
python agent.py --approve <post_id>       # approve and post
python agent.py --reject <post_id>        # discard
```

**Option 2 — Web UI:**
Open `http://localhost:8000/drafts` → review → edit in the text area → click Approve.

**Option 3 — Email (if SMTP configured):**
Click the "Approve & Post" link in the email notification.

---

## Output Format (Draft JSON)

```json
{
  "post_id": "a1b2c3d4",
  "title": "Why AI Agents Are Eating Software",
  "body": "Full post text, 150–300 words...",
  "hashtags": ["AI", "MachineLearning", "SoftwareEngineering"],
  "hook": "The first sentence — the attention-grabber",
  "cta": "The call-to-action line",
  "sources": {
    "videos": [{"title": "...", "url": "..."}],
    "news": [{"title": "...", "url": "..."}]
  },
  "status": "pending_approval",
  "queued_at": "2026-04-03T12:00:00+00:00"
}
```

---

## Edge Cases & Known Constraints

### LinkedIn API
- Uses the **Articles API** (`POST /rest/articles`) — this is what creates a real newsletter article that notifies subscribers. It is NOT the same as a regular post.
- Required OAuth scope: `w_member_social`. You must also be the owner/admin of the newsletter.
- Access tokens expire every 60 days. Refresh via the LinkedIn Developer Portal.
- If you get a **403**: your token is missing `w_member_social` scope, or you're not the newsletter owner.
- If you get a **422**: the newsletter URN is wrong, or the HTML body has unsupported tags. Use only `<p>`, `<br>`, `<strong>` tags.
- The `LinkedIn-Version` header is set to `202410`. If LinkedIn rejects it, bump this value in `tools/post_linkedin.py`.
- Rate limit: 100 requests/day on the free developer tier.

### YouTube RSS
- RSS feeds update with a delay of ~10 minutes after publishing.
- Private/unlisted videos won't appear in the RSS feed.
- If the channel ID is wrong, the RSS returns an empty feed (not an error).

### Claude API
- Uses `claude-opus-4-6` with adaptive thinking for best draft quality.
- Typical cost: ~$0.05–$0.15 per draft (depends on news context length).
- If the draft JSON is malformed, `generate_draft.py` wraps the raw text as a fallback.

### News Feeds
- Some RSS feeds return partial HTML in summaries — the tool strips tags automatically.
- If all feeds fail, the draft is generated from video context alone.

---

## Self-Improvement Log

| Date | Issue | Fix Applied |
|------|-------|-------------|
| — | — | — |

*(Update this table when you find issues or discover better approaches)*
