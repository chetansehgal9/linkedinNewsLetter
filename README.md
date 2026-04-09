# LinkedIn Post Generator

Automated AI-focused LinkedIn post pipeline built on the **WAT framework** (Workflows, Agents, Tools). Every Monday it fetches the latest AI news, generates a LinkedIn post draft using Claude, opens a GitHub Issue for your approval, and cross-posts to LinkedIn and Dev.to when you comment `post`.

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                     GitHub Actions                          │
│                                                             │
│  [Schedule: Mon 9am]  ──►  generate_draft.yml              │
│  [Issue comment]      ──►  approve_draft.yml               │
│  [Issue comment]      ──►  post_to_linkedin.yml            │
│  [Issue comment]      ──►  recreate_draft.yml              │
└────────────────────────────┬────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │    agent.py     │  ← WAT Layer 2: Orchestrator
                    │  (Coordinator)  │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                   │                    │
┌───────▼──────┐  ┌─────────▼──────┐  ┌──────────▼──────────┐
│  fetch_news  │  │generate_draft  │  │  generate_image     │
│  fetch_youtube│  │generate_blog   │  │  post_linkedin      │
│              │  │                │  │  post_devto         │
│  (RSS/YT)    │  │  (Claude)      │  │  (APIs)             │
└──────────────┘  └────────────────┘  └─────────────────────┘
    WAT Layer 3: Deterministic Tools
```

The WAT framework separates concerns:

| Layer | What it is | Example |
| --- | --- | --- |
| **Workflows** | Markdown SOPs defining objectives and steps | `workflows/linkedin_post_generator.md` |
| **Agent** | Orchestrator that reads the SOP and coordinates tools | `agent.py` |
| **Tools** | Python scripts that do the actual work | `tools/fetch_news.py`, `tools/post_linkedin.py` |

---

## How the Pipeline Works

### 1. Draft Generation (`generate_draft.yml`)

Runs every **Monday at 9am UTC** (or manually via `workflow_dispatch`):

1. **Fetch news** — `tools/fetch_news.py` pulls the latest articles from AI-focused RSS feeds (Import AI, Last Week in AI, TLDR AI, Hugging Face Blog)
2. **Generate draft** — `tools/generate_draft.py` sends news to Claude with a strict AI-only system prompt; Claude returns a structured JSON draft (avoids recently posted topics)
3. **Create GitHub Issue** — `.github/scripts/create_issue.js` opens an issue labeled `linkedin-draft` with the formatted post body and an embedded JSON blob for later extraction

### 2. Image Preview (`approve_draft.yml`)

Triggered when **you comment `approve`** on the draft issue:

1. Extracts the draft JSON from the issue body (respects any edits you made to the visible text)
2. Fetches a relevant photo from Unsplash based on the post topic
3. Commits the image to `assets/drafts/preview.jpg` in the repo
4. Replies with the image preview and instructions to comment `post` to publish

### 3. Publishing (`post_to_linkedin.yml`)

Triggered when **you comment `post`** (or `post-no-image`) on the draft issue:

1. **Expand to blog** — `tools/generate_blog.py` uses Claude to expand the ~150-word LinkedIn post into a full ~800-word article
2. **Cross-post to Dev.to** — `tools/post_devto.py` publishes the blog with the Unsplash image as cover; returns the article URL
3. **Post to LinkedIn** — `tools/post_linkedin.py` posts the draft with the Dev.to link appended and the Unsplash image attached (skipped if `post-no-image`)
4. **Track topic** — Appends the post topic to `assets/posted_topics.txt` to prevent future duplicates
5. Closes the issue with a ✅ reaction

### 4. Regeneration Flow (`recreate_draft.yml`)

Triggered when **you comment `recreate: [feedback]`** on the draft issue:

1. Extracts the original draft JSON + your feedback from the issue body
2. Calls Claude again with the same sources + your feedback as revision instructions
3. Updates the issue body with the new draft
4. Posts a confirmation comment — you can then `approve` the revised version

### 5. Stale Issue Cleanup

When a new draft is generated, any previously open `linkedin-draft` issues are automatically closed so only one draft is active at a time.

---

## File Structure

```text
├── agent.py                          # Main orchestrator (WAT Layer 2)
├── tools/
│   ├── fetch_news.py                 # RSS feed fetcher (AI-focused feeds)
│   ├── fetch_youtube.py              # YouTube video metadata fetcher
│   ├── generate_draft.py             # Claude draft generator
│   ├── generate_blog.py              # Expands post to ~800-word blog article (Claude)
│   ├── generate_image.py             # Fetches Unsplash image based on post topic
│   ├── post_linkedin.py              # LinkedIn Posts API publisher
│   ├── post_devto.py                 # Dev.to publisher (Forem API)
│   ├── post_hashnode.py              # Hashnode publisher (GraphQL API, unused)
│   ├── post_medium.py                # Medium publisher (DEPRECATED — API removed)
│   └── notify.py                     # Local draft queue (for non-Actions use)
├── workflows/
│   ├── linkedin_post_generator.md    # SOP for the full pipeline
│   └── writing_style.md             # Your voice and style guide for Claude
├── .github/
│   ├── workflows/
│   │   ├── generate_draft.yml        # Weekly draft generation
│   │   ├── approve_draft.yml         # Image generation on "approve" comment
│   │   ├── post_to_linkedin.yml      # Publish on "post" comment
│   │   └── recreate_draft.yml        # Regenerate with feedback on comment
│   └── scripts/
│       ├── create_issue.js           # Creates the GitHub approval issue
│       └── update_issue.js           # Updates issue body after regeneration
├── assets/
│   ├── posted_topics.txt             # Topic history for deduplication
│   └── drafts/preview.jpg            # Latest draft image preview (auto-committed)
├── .env                              # API keys (never committed)
└── requirements.txt
```

---

## Setup

### Required Secrets (GitHub → Settings → Secrets)

| Secret | Description |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude API key |
| `LINKEDIN_ACCESS_TOKEN` | LinkedIn OAuth token with `w_member_social` scope |
| `UNSPLASH_ACCESS_KEY` | Unsplash API key for post preview images |
| `DEVTO_API_KEY` | Dev.to API key for cross-posting (optional) |

### Required Variables (GitHub → Settings → Variables)

| Variable | Description |
| --- | --- |
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

| Comment | Effect |
| --- | --- |
| `approve` | Fetches Unsplash image preview; posts it as a comment with instructions |
| `post` | Expands to blog → publishes to Dev.to → posts to LinkedIn → closes issue |
| `post-no-image` | Same as `post` but skips image attachment on LinkedIn |
| `recreate: [feedback]` | Regenerates draft with your feedback |
| Edit issue body | Edits are respected when posting — change the visible text before commenting `post` |
| Close issue | Discards the draft |

---

## Topic Deduplication

After each successful post, the topic is appended to `assets/posted_topics.txt`. On the next draft generation, `generate_draft.py` reads this file and instructs Claude to avoid covering the same ground. This keeps your feed varied week to week.

---

## Cross-Posting to Dev.to

When you comment `post`, the pipeline automatically:

1. Uses Claude to expand the LinkedIn post into a full blog article (~800 words)
2. Publishes the article to Dev.to with the Unsplash preview image as the cover photo
3. Appends the Dev.to article URL to the LinkedIn post body

If `DEVTO_API_KEY` is not set, this step is skipped and LinkedIn is posted standalone.

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
