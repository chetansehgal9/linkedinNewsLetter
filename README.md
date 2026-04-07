# LinkedIn Post Generator

Automated AI-focused LinkedIn post pipeline built on the **WAT framework** (Workflows, Agents, Tools). Every Monday it fetches the latest AI news, generates a LinkedIn post draft using Claude, opens a GitHub Issue for your approval, and posts to LinkedIn when you comment `approve`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     GitHub Actions                          │
│                                                             │
│  [Schedule: Mon 9am]  ──►  generate_draft.yml              │
│  [Issue comment]      ──►  post_to_linkedin.yml            │
│  [Issue comment]      ──►  recreate_draft.yml              │
└────────────────────────────┬────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │    agent.py     │  ← WAT Layer 2: Orchestrator
                    │  (Coordinator)  │
                    └────────┬────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
  ┌───────▼──────┐  ┌────────▼──────┐  ┌───────▼───────┐
  │ fetch_news   │  │generate_draft │  │post_linkedin  │
  │    .py       │  │    .py        │  │    .py        │
  │ (RSS feeds)  │  │(Claude Opus)  │  │(LinkedIn API) │
  └──────────────┘  └───────────────┘  └───────────────┘
      WAT Layer 3: Deterministic Tools
```

The WAT framework separates concerns:

| Layer | What it is | Example |
|---|---|---|
| **Workflows** | Markdown SOPs defining objectives and steps | `workflows/linkedin_post_generator.md` |
| **Agent** | Orchestrator that reads the SOP and coordinates tools | `agent.py` |
| **Tools** | Python scripts that do the actual work | `tools/fetch_news.py`, `tools/post_linkedin.py` |

---

## How the Pipeline Works

### 1. Draft Generation (`generate_draft.yml`)

Runs every **Monday at 9am UTC** (or manually via `workflow_dispatch`):

1. **Fetch news** — `tools/fetch_news.py` pulls the latest articles from AI-focused RSS feeds (Import AI, Last Week in AI, TLDR AI, Hugging Face Blog)
2. **Generate draft** — `tools/generate_draft.py` sends news to Claude Opus with a strict AI-only system prompt; Claude returns a structured JSON draft
3. **Create GitHub Issue** — `.github/scripts/create_issue.js` opens an issue labeled `linkedin-draft` with the formatted post body and an embedded JSON blob for later extraction

### 2. Approval Flow (`post_to_linkedin.yml`)

Triggered when **you comment on the draft issue**:

- Comment `approve` → posts the draft to LinkedIn and closes the issue
- The post body includes hashtags (appended once) and a newsletter CTA link

### 3. Regeneration Flow (`recreate_draft.yml`)

Triggered when **you comment `recreate: [feedback]`** on the draft issue:

1. Extracts the original draft JSON from the issue body
2. Calls Claude again with the same sources + your feedback as revision instructions
3. Updates the issue body with the new draft
4. Posts a confirmation comment — you can then `approve` the revised version

### 4. Stale Issue Cleanup

When a new draft is generated, any previously open `linkedin-draft` issues are automatically closed so only one draft is active at a time.

---

## File Structure

```
├── agent.py                          # Main orchestrator (WAT Layer 2)
├── tools/
│   ├── fetch_news.py                 # RSS feed fetcher (AI-focused feeds)
│   ├── fetch_youtube.py              # YouTube video metadata fetcher
│   ├── generate_draft.py             # Claude Opus draft generator
│   ├── post_linkedin.py              # LinkedIn Posts API publisher
│   └── notify.py                     # Local draft queue (for non-Actions use)
├── workflows/
│   ├── linkedin_post_generator.md    # SOP for the full pipeline
│   └── writing_style.md             # Your voice and style guide for Claude
├── .github/
│   ├── workflows/
│   │   ├── generate_draft.yml        # Weekly draft generation
│   │   ├── post_to_linkedin.yml      # Approve and post on comment
│   │   └── recreate_draft.yml        # Regenerate with feedback on comment
│   └── scripts/
│       ├── create_issue.js           # Creates the GitHub approval issue
│       └── update_issue.js           # Updates issue body after regeneration
├── .env                              # API keys (never committed)
└── requirements.txt
```

---

## Setup

### Required Secrets (GitHub → Settings → Secrets)

| Secret | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `LINKEDIN_ACCESS_TOKEN` | LinkedIn OAuth token with `w_member_social` scope |

### Required Variables (GitHub → Settings → Variables)

| Variable | Description |
|---|---|
| `LINKEDIN_PERSON_URN` | Your LinkedIn person URN (`urn:li:person:XXXXXXXX`) |
| `LINKEDIN_NEWSLETTER_URN` | Your newsletter URN for the CTA link (optional) |
| `YOUTUBE_CHANNEL_ID` | Your YouTube channel ID (optional) |
| `NEWS_RSS_FEEDS` | Comma-separated RSS feed URLs (falls back to AI defaults) |

### Local Development

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in your keys

# Full pipeline (dry run — no issue created, no post)
python agent.py --run --dry-run

# Generate and save draft to file
python agent.py --run --output .tmp/draft.json

# Regenerate with feedback
python agent.py --regenerate \
  --draft-file .tmp/draft.json \
  --feedback "make it shorter, focus on the cost tradeoff" \
  --output .tmp/new_draft.json

# Post a draft directly
python tools/post_linkedin.py --draft-file .tmp/draft.json --dry-run
```

---

## Approval Workflow (GitHub Issues)

Each draft opens as a GitHub Issue with label `linkedin-draft`:

| Action | How |
|---|---|
| Post as-is | Comment `approve` |
| Edit then post | Edit the issue body, then comment `approve` |
| Regenerate with changes | Comment `recreate: [your feedback here]` |
| Discard | Close the issue |

---

## Content Focus

All posts are exclusively AI-focused: LLMs, model releases, AI agents, inference infrastructure, RAG, fine-tuning, AI safety, multimodal models, and how AI is changing how engineers build. Non-AI topics are explicitly excluded from the system prompt.

Default RSS feeds (all AI-specific):
- [Import AI](https://importai.substack.com/feed) — AI research weekly
- [Last Week in AI](https://lastweekin.ai/feed) — news roundup
- [TLDR AI](https://tldr.tech/api/rss/ai) — curated AI news
- [Hugging Face Blog](https://huggingface.co/blog/feed.xml) — models and tools

---

## LinkedIn API Note

This pipeline uses the **LinkedIn Posts API** (`/rest/posts`) which is available to all developer apps with the `w_member_social` scope. The Newsletter Articles API (`/rest/articles`) requires Marketing Developer Platform partner approval and is not used here. Instead, a newsletter CTA link is appended to each post.
