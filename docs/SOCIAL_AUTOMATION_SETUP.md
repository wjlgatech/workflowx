# Social Automation Setup — LinkedIn + X
*Post from Claude directly. No copy-paste.*

## Architecture

```
Claude → workflowx_post_social MCP tool
              ↓
    ┌─────────┴──────────┐
    │                    │
LinkedIn              X / Twitter
(Playwright)          (tweepy v4)
browser automation    official API v2
~free, no ban risk    ~$0.01/tweet
```

---

## LinkedIn Setup (One-Time)

### Step 1 — Install Playwright

```bash
cd ~/Documents/Projects/workflowx
pip install playwright
playwright install chromium
```

### Step 2 — Save your LinkedIn session (run once)

```bash
python -c "
import asyncio
from workflowx.social.linkedin_poster import LinkedInPoster
p = LinkedInPoster()
asyncio.run(p.save_session('wjlgatech@gmail.com', 'YOUR_LINKEDIN_PASSWORD'))
"
```

A real Chrome window opens. Sign in manually if prompted (LinkedIn may require 2FA). Session saved to `~/.workflowx/linkedin_cookies.json`.

**Cookies last ~1 year.** Re-run this once if posting fails.

### Step 3 — Test LinkedIn posting

```bash
python -c "
import asyncio
from workflowx.social.linkedin_poster import LinkedInPoster
p = LinkedInPoster()
result = asyncio.run(p.post('Test post from WorkflowX automation. Ignore.'))
print(result)
"
```

---

## X / Twitter Setup

### Step 1 — Get X API credentials

1. Go to [developer.twitter.com](https://developer.twitter.com)
2. Create a new app (or use existing)
3. Go to **Keys and Tokens**
4. Generate **Access Token + Secret** (with Read+Write permissions)
5. Copy: API Key, API Key Secret, Access Token, Access Token Secret

### Step 2 — Add to environment

Add to `~/.zshrc` (or `~/.bash_profile`):

```bash
export TWITTER_API_KEY="your_api_key"
export TWITTER_API_SECRET="your_api_key_secret"
export TWITTER_ACCESS_TOKEN="your_access_token"
export TWITTER_ACCESS_TOKEN_SECRET="your_access_token_secret"
```

Then: `source ~/.zshrc`

### Step 3 — Test X posting

```bash
python -c "
from workflowx.social.twitter_poster import TwitterPoster
import os
p = TwitterPoster(
    os.environ['TWITTER_API_KEY'],
    os.environ['TWITTER_API_SECRET'],
    os.environ['TWITTER_ACCESS_TOKEN'],
    os.environ['TWITTER_ACCESS_TOKEN_SECRET'],
)
result = p.post_tweet('Testing WorkflowX social automation. #BuildingInPublic')
print(result)
"
```

**Cost**: ~$0.01 per tweet on the Basic X API tier.

---

## Claude Desktop MCP Config

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "workflowx": {
      "command": "python",
      "args": ["-m", "workflowx.mcp_server"],
      "env": {
        "WORKFLOWX_DATA_DIR": "~/.workflowx",
        "TWITTER_API_KEY": "your_key",
        "TWITTER_API_SECRET": "your_secret",
        "TWITTER_ACCESS_TOKEN": "your_token",
        "TWITTER_ACCESS_TOKEN_SECRET": "your_token_secret"
      }
    }
  }
}
```

Restart Claude Desktop. You'll now have these MCP tools:

```
workflowx_post_social    — post to linkedin, twitter, or both
workflowx_list_post_queue — see pending scheduled posts
workflowx_process_post_queue — fire any due posts
```

---

## Usage from Claude

```
"Post this to LinkedIn: [paste text]"
→ workflowx_post_social(platform="linkedin", text="...")

"Post this thread to X: [3 tweets]"
→ workflowx_post_social(platform="twitter", text="tweet1\n---\ntweet2\n---\ntweet3")

"Schedule this LinkedIn post for tomorrow 9am:"
→ workflowx_post_social(platform="linkedin", text="...", schedule_for="2026-04-07T09:00:00")

"Post the Meeting Intelligence Stack article to both platforms"
→ workflowx_post_social(platform="both", text="[article]", url="https://github.com/wjlgatech/workflowx")
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| LinkedIn post fails | Re-run `save_session()` — cookies expired |
| LinkedIn bot detection | Add `headless=False` to `post()` call temporarily |
| Twitter 403 | Check app has **Read + Write** permissions, not just Read |
| Twitter 401 | Regenerate Access Token (not just API keys) |
| `playwright not found` | `pip install playwright && playwright install chromium` |

---

*Files: `src/workflowx/social/` — linkedin_poster.py, twitter_poster.py, post_scheduler.py, mcp_tools.py*
*Tests: `tests/test_social.py` — 22 tests, 0 API calls*
