# Setup Guide - PR Review Agent

Complete setup instructions for getting the PR Review Agent running on your machine.

## Prerequisites

Before you begin, ensure you have:

- **Python 3.8 or higher** installed
- **GitHub CLI (gh)** installed and authenticated
- **Git** installed
- A **GitHub account** with repository access
- An **Anthropic API key** (or access to Claude API)

## Step 1: Clone the Repository

```bash
git clone <repository-url>
cd ReviewPulse
```

## Step 2: Run Setup Script

The easiest way to set up is using the provided script:

```bash
chmod +x setup.sh
./setup.sh
```

This will:
- Check Python version
- Create a virtual environment
- Install all dependencies

Or manually:

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Step 3: Configure Environment Variables

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Edit `.env` with your credentials:

```bash
# Open in your preferred editor
nano .env
# or
vim .env
# or
open .env  # macOS
```

3. Add your API keys:

```env
# Required
GITHUB_TOKEN=ghp_your_actual_github_token
ANTHROPIC_API_KEY=sk-ant-your_actual_anthropic_key

# Optional - for custom endpoints
ANTHROPIC_BASE_URL=https://your-custom-endpoint.com

# Optional - model selection
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```

### Getting Your GitHub Token

1. Go to https://github.com/settings/tokens
2. Click "Generate new token (classic)"
3. Select scopes:
   - `repo` (full control of private repositories)
   - `read:org` (read org and team membership)
4. Generate and copy the token
5. Paste it in your `.env` file

### Getting Your Anthropic API Key

1. Go to https://console.anthropic.com/
2. Sign up or log in
3. Navigate to API Keys section
4. Create a new API key
5. Copy and paste it in your `.env` file

## Step 4: Authenticate GitHub CLI

Run the authentication command:

```bash
gh auth login
```

Follow the prompts to authenticate with your GitHub account.

## Step 5: Test the Setup

Run a dry-run test to verify everything works:

```bash
# Test with a public PR (dry run - won't post comments)
python src/review_pr.py https://github.com/owner/repo/pull/123 --dry-run
```

Expected output:
```
╔══════════════════════════════════════════════════════════════╗
║                   PR Review Agent v1.0                       ║
╚══════════════════════════════════════════════════════════════╝

🔧 Initializing...
   Initializing LLM reviewer...
   ✓ LLM reviewer initialized

🔗 Parsing: https://github.com/owner/repo/pull/123
   owner/repo#123

📥 Fetching PR...
   Diff: XXXXX chars
   Files: X

🤖 Generating review...
   Generated: X issues
   Valid comments: X

🏃 DRY RUN - not posting

Comments that would be posted:
   🔴 file.rs:42 (high)
      Issue description...
```

## Usage

### Basic Usage

```bash
# Dry run (review only, don't post)
python src/review_pr.py https://github.com/owner/repo/pull/123

# Post comments to GitHub
POST_COMMENTS=true python src/review_pr.py https://github.com/owner/repo/pull/123

# Using the shell script
./review_pr.sh https://github.com/owner/repo/pull/123 --post

# Different URL formats supported
python src/review_pr.py owner/repo#123
python src/review_pr.py owner/repo/pull/123
```

### Advanced Options

```bash
# Limit number of comments
python src/review_pr.py <URL> --max-comments 10

# Force dry run (even if POST_COMMENTS is set)
python src/review_pr.py <URL> --dry-run
```

## Claude Desktop Integration (Optional)

To use this as a Claude Desktop agent:

1. Open Claude Desktop
2. Go to Settings → Developer → Edit Config
3. Update the configuration file:

```json
{
  "mcpServers": {
    "pr-reviewer": {
      "command": "/full/path/to/ReviewPulse/venv/bin/python",
      "args": ["/full/path/to/ReviewPulse/src/mcp_server.py"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}",
        "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}",
        "POST_COMMENTS": "false",
        "SKILLS_PATH": "/full/path/to/ReviewPulse/skills/skill.md"
      }
    }
  }
}
```

4. Restart Claude Desktop
5. You can now ask Claude to review PRs:
   - "Review this PR: https://github.com/owner/repo/pull/123"

## Troubleshooting

### "GITHUB_TOKEN not found"
- Ensure `.env` file exists in the project root
- Check that the token is set correctly (no quotes needed)
- Run `source .env` to load variables

### "Failed to fetch PR diff"
- Verify your GitHub token has `repo` scope
- Check that the PR URL is correct and accessible
- Ensure you're authenticated: `gh auth status`

### "No comments posted"
- Set `POST_COMMENTS=true` in your `.env` file
- Or use `--post` flag with the shell script
- Check that you have write access to the repository

### "AI API key required"
- Ensure ANTHROPIC_API_KEY is set in `.env`
- Verify the key is valid at https://console.anthropic.com/

### Import Errors
- Ensure virtual environment is activated
- Reinstall dependencies: `pip install -r requirements.txt`

## Next Steps

- Customize your review guidelines in `skills/skill.md`
- Set up a CI/CD pipeline to automate reviews
- Configure rate limiting for large PRs
- Join our community for support and updates

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the main README.md
3. Open an issue on GitHub

## Security Notes

- Never commit your `.env` file
- Keep API keys private and rotate them regularly
- Use GitHub tokens with minimal required scopes
- The `.gitignore` file is already configured to exclude sensitive files
