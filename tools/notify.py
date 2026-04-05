#!/usr/bin/env python3
"""
Save a draft to the pending queue and notify the user for approval via email.

Approval links include a secure token so only you can approve/reject,
even when the server is publicly deployed.

Usage:
    python tools/notify.py --draft-file .tmp/draft.json
    python tools/notify.py --draft '{"title":"...", "body":"..."}'
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PENDING_DIR = Path(__file__).parent.parent / ".tmp" / "pending_posts"


# ── Security: approval tokens ──────────────────────────────────────────────────

def _approval_secret() -> str:
    """Return the secret used to sign approval tokens. Falls back to webhook secret."""
    return os.getenv("APPROVAL_SECRET") or os.getenv("GITHUB_WEBHOOK_SECRET") or "change-me-in-env"


def generate_token(post_id: str, action: str) -> str:
    """Generate a signed token for approve/reject links."""
    msg = f"{post_id}:{action}".encode()
    return hmac.new(_approval_secret().encode(), msg, hashlib.sha256).hexdigest()[:24]


def verify_token(post_id: str, action: str, token: str) -> bool:
    """Verify an approval token is valid."""
    expected = generate_token(post_id, action)
    return hmac.compare_digest(expected, token)


# ── Queue management ───────────────────────────────────────────────────────────

def save_pending(draft: dict) -> str:
    """Save draft to pending queue. Returns the post_id."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    post_id = str(uuid.uuid4())[:8]
    draft["post_id"] = post_id
    draft["queued_at"] = datetime.now(timezone.utc).isoformat()
    draft["status"] = "pending_approval"

    path = PENDING_DIR / f"{post_id}.json"
    path.write_text(json.dumps(draft, indent=2))
    return post_id


def list_pending() -> list[dict]:
    """Return all pending drafts sorted by queue time."""
    if not PENDING_DIR.exists():
        return []
    drafts = []
    for path in PENDING_DIR.glob("*.json"):
        try:
            drafts.append(json.loads(path.read_text()))
        except Exception:
            pass
    return sorted(drafts, key=lambda d: d.get("queued_at", ""), reverse=True)


def load_pending(post_id: str) -> dict | None:
    """Load a specific pending draft by ID."""
    path = PENDING_DIR / f"{post_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def mark_processed(post_id: str, outcome: str) -> None:
    """Update draft status and move to processed folder."""
    path = PENDING_DIR / f"{post_id}.json"
    if not path.exists():
        return
    draft = json.loads(path.read_text())
    draft["status"] = outcome
    draft["processed_at"] = datetime.now(timezone.utc).isoformat()

    processed_dir = PENDING_DIR.parent / "processed_posts"
    processed_dir.mkdir(parents=True, exist_ok=True)
    (processed_dir / f"{post_id}.json").write_text(json.dumps(draft, indent=2))
    path.unlink()


# ── Notifications ──────────────────────────────────────────────────────────────

def _approval_urls(post_id: str, base_url: str) -> tuple[str, str]:
    """Return (approve_url, reject_url) with signed tokens."""
    approve_token = generate_token(post_id, "approve")
    reject_token  = generate_token(post_id, "reject")
    return (
        f"{base_url}/drafts/{post_id}/approve?token={approve_token}",
        f"{base_url}/drafts/{post_id}/reject?token={reject_token}",
    )


def notify_console(draft: dict, post_id: str, base_url: str) -> None:
    """Print approval instructions to the terminal."""
    title    = draft.get("title", "Untitled")
    body     = draft.get("body", "")
    hashtags = " ".join(f"#{t}" for t in draft.get("hashtags", []))
    approve_url, reject_url = _approval_urls(post_id, base_url)

    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  NEW DRAFT READY FOR APPROVAL  (ID: {post_id})")
    print(sep)
    print(f"\nTitle: {title}\n")
    print(body)
    if hashtags:
        print(f"\n{hashtags}")
    print(f"\n{sep}")
    print(f"  Approve : {approve_url}")
    print(f"  Reject  : {reject_url}")
    print(f"  CLI     : python agent.py --approve {post_id}")
    print(sep + "\n")


def notify_email(draft: dict, post_id: str, base_url: str) -> None:
    """Send approval email with one-click approve/reject buttons."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    smtp_host    = os.getenv("SMTP_HOST", "")
    smtp_port    = int(os.getenv("SMTP_PORT", "587"))
    smtp_user    = os.getenv("SMTP_USER", "")
    smtp_pass    = os.getenv("SMTP_PASS", "")
    notify_to    = os.getenv("NOTIFY_EMAIL", smtp_user)

    if not all([smtp_host, smtp_user, smtp_pass, notify_to]):
        print("  (Email not configured — skipping. Set SMTP_* vars in .env to enable.)", file=sys.stderr)
        return

    title        = draft.get("title", "New LinkedIn Post Draft")
    body         = draft.get("body", "")
    hashtags     = " ".join(f"#{t}" for t in draft.get("hashtags", []))
    approve_url, reject_url = _approval_urls(post_id, base_url)

    full_text    = f"{body}\n\n{hashtags}".strip()

    html = f"""
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             max-width:600px;margin:0 auto;padding:20px;color:#1a1a1a">

  <h2 style="color:#0077b5;margin-bottom:4px">{title}</h2>
  <p style="color:#888;font-size:13px;margin-top:0">LinkedIn Newsletter Draft · {post_id}</p>

  <div style="background:#f7f7f7;border:1px solid #ddd;border-radius:8px;
              padding:20px;white-space:pre-wrap;font-size:15px;line-height:1.7;
              margin:20px 0">{full_text}</div>

  <table cellpadding="0" cellspacing="0" style="margin:24px 0">
    <tr>
      <td style="padding-right:12px">
        <a href="{approve_url}"
           style="display:inline-block;background:#0077b5;color:white;
                  padding:12px 28px;text-decoration:none;border-radius:6px;
                  font-weight:600;font-size:15px">
          ✅ Approve &amp; Post
        </a>
      </td>
      <td>
        <a href="{reject_url}"
           style="display:inline-block;background:#cc0000;color:white;
                  padding:12px 28px;text-decoration:none;border-radius:6px;
                  font-weight:600;font-size:15px">
          ❌ Reject
        </a>
      </td>
    </tr>
  </table>

  <p style="color:#aaa;font-size:12px;border-top:1px solid #eee;padding-top:12px">
    These links are signed and can only be used once.<br>
    To edit before posting, open:
    <a href="{base_url}/drafts/{post_id}" style="color:#0077b5">
      {base_url}/drafts/{post_id}
    </a>
  </p>

</body>
</html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[LinkedIn Draft] {title}"
    msg["From"]    = smtp_user
    msg["To"]      = notify_to
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, notify_to, msg.as_string())
        print(f"  Email sent to {notify_to}", file=sys.stderr)
    except Exception as e:
        print(f"WARNING: Email failed: {e}", file=sys.stderr)


def notify(draft: dict) -> str:
    """Save draft, print to console, send email. Returns post_id."""
    base_url = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000")
    post_id  = save_pending(draft)
    notify_console(draft, post_id, base_url)
    notify_email(draft, post_id, base_url)
    return post_id


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Notify user of new draft for approval")
    parser.add_argument("--draft-file", help="Path to draft JSON file")
    parser.add_argument("--draft",      help="Draft JSON string")
    parser.add_argument("--list", action="store_true", help="List all pending drafts")
    args = parser.parse_args()

    if args.list:
        pending = list_pending()
        if not pending:
            print("No pending drafts.")
        for d in pending:
            print(f"[{d['post_id']}] {d.get('title', 'Untitled')} — {d.get('queued_at', '')}")
        return

    if args.draft_file:
        draft = json.loads(Path(args.draft_file).read_text())
    elif args.draft:
        draft = json.loads(args.draft)
    else:
        print("ERROR: Provide --draft-file or --draft", file=sys.stderr)
        sys.exit(1)

    post_id = notify(draft)
    print(post_id)


if __name__ == "__main__":
    main()
