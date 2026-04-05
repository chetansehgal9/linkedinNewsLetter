// Called by recreate_draft.yml after the draft is regenerated.
// Reads .tmp/new_draft.json and updates the existing GitHub Issue body.

const fs = require('fs');
const path = require('path');

module.exports = async ({ github, context }) => {
  const draftPath = path.join(process.env.GITHUB_WORKSPACE || '.', '.tmp', 'new_draft.json');
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
    '### How to approve',
    '- ✅ **Approve & post:** Comment `approve` on this issue',
    '- ✏️ **Edit then approve:** Edit the post text above, then comment `approve`',
    '- 🔄 **Regenerate with feedback:** Comment `recreate: [your feedback]`',
    '- ❌ **Reject:** Simply close this issue',
    '',
    hiddenJson,
  ].join('\n');

  await github.rest.issues.update({
    owner:        context.repo.owner,
    repo:         context.repo.repo,
    issue_number: context.payload.issue.number,
    title:        `[LinkedIn Draft] ${title}`,
    body:         issueBody,
  });

  console.log(`Issue #${context.payload.issue.number} updated with new draft: ${title}`);
};
