// Called by generate_draft.yml after the draft is generated.
// Reads .tmp/draft.json and opens a GitHub Issue for approval.

const fs = require('fs');
const path = require('path');

module.exports = async ({ github, context }) => {
  const draftPath = path.join(process.env.GITHUB_WORKSPACE || '.', '.tmp', 'draft.json');
  const draft = JSON.parse(fs.readFileSync(draftPath, 'utf8'));

  const title    = draft.title || 'Untitled';
  const body     = draft.body  || '';
  const tags     = (draft.hashtags || []).map(t => `#${t.replace(/^#/, '')}`).join(' ');
  const fullPost = tags ? `${body}\n\n${tags}` : body;

  const videoLines = (draft.sources?.videos || [])
    .map(v => `- 🎥 [${v.title}](${v.url})`).join('\n') || '_No videos_';
  const newsLines  = (draft.sources?.news  || [])
    .map(n => `- 📰 [${n.title}](${n.url})`).join('\n') || '_No news_';

  // Embed the full draft JSON so the post workflow can extract it
  const hiddenJson = `<!-- DRAFT_JSON\n${JSON.stringify(draft)}\nDRAFT_JSON -->`;

  // Blog preview section
  const blog = draft.blog || {};
  const blogPreview = blog.body ? blog.body.slice(0, 400) + '...' : '_Not generated_';
  const blogSection = [
    '<details>',
    '<summary>📝 Blog Article Preview (Hashnode + Dev.to)</summary>',
    '',
    `**Title:** ${blog.title || title}`,
    `**Tags:** ${(blog.tags || []).join(', ')}`,
    '',
    blogPreview,
    '',
    '</details>',
  ].join('\n');

  const issueBody = [
    '## 📝 LinkedIn Draft Ready for Approval',
    '',
    `**Title:** ${title}`,
    '',
    '---',
    '',
    fullPost,
    '',
    '---',
    '',
    '### Sources',
    videoLines,
    newsLines,
    '',
    '---',
    '',
    blogSection,
    '',
    '---',
    '',
    '### How to approve',
    '- ✅ **Step 1 — Generate image preview:** Comment `approve`',
    '- 📸 **Step 2 — Publish to LinkedIn + Hashnode + Dev.to:** Comment `post` after reviewing the image',
    '- 🚀 **Post without image:** Comment `post-no-image` to skip image generation',
    '- ✏️ **Edit then approve:** Edit the post text above, then comment `approve`',
    '- 🔄 **Regenerate with feedback:** Comment `recreate: [your feedback]`',
    '- ❌ **Reject:** Simply close this issue',
    '',
    hiddenJson,
  ].join('\n');

  // Close any previously open draft issues so only one is active at a time
  const existing = await github.rest.issues.listForRepo({
    owner:  context.repo.owner,
    repo:   context.repo.repo,
    labels: 'linkedin-draft',
    state:  'open',
  });
  for (const old of existing.data) {
    await github.rest.issues.update({
      owner:        context.repo.owner,
      repo:         context.repo.repo,
      issue_number: old.number,
      state:        'closed',
      state_reason: 'not_planned',
    });
    console.log(`Closed stale draft issue #${old.number}`);
  }

  const issue = await github.rest.issues.create({
    owner:  context.repo.owner,
    repo:   context.repo.repo,
    title:  `[LinkedIn Draft] ${title}`,
    body:   issueBody,
    labels: ['linkedin-draft'],
  });

  console.log(`Issue created: ${issue.data.html_url}`);
};
