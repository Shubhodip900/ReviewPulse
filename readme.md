# PR Review Agent

AI-powered code review for GitHub Pull Requests using Claude AI. Automatically analyzes code changes and posts contextual comments on PRs.

## Overview

This tool automates code reviews by:
1. Fetching PR diffs from GitHub
2. Analyzing code changes using AI
3. Posting review comments directly on specific lines
4. Using customizable review guidelines from skills files

## Quick Start

```bash
# Clone and setup
git clone <repository-url>
cd ReviewPulse
./setup.sh

# Configure API keys
cp .env.example .env
# Edit .env with your GitHub and Anthropic API keys

# Run a review
python src/review_pr.py https://github.com/owner/repo/pull/123
```

See [SETUP.md](SETUP.md) for detailed installation instructions.

## Architecture

### System Components

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   GitHub API    │────▶│  PR Review Agent │────▶│  Claude AI API  │
│   (PR/Diff)     │     │                  │     │ (Code Analysis) │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────┐
                        │  Skills DB   │
                        │ (Review      │
                        │ Guidelines)  │
                        └──────────────┘
```

### Component Details

#### 1. **GitHub Client** (`src/github_client.py`)
Handles all GitHub interactions:
- **DiffParser**: Parses PR diffs to identify changed lines and file positions
- **GitHubClient**: Uses GitHub CLI (`gh`) to fetch PR data and post reviews
- **Line Mapping**: Accurately maps diff positions to actual file line numbers

Key features:
- Converts PR URLs to owner/repo/number tuples
- Extracts added/modified lines from diffs
- Posts review comments in pending state (batch mode)
- Handles existing pending reviews

#### 2. **LLM Reviewer** (`src/llm_reviewer.py`)
AI-powered code analysis engine:
- **ReviewComment**: Dataclass for individual review findings
- **ReviewSummary**: Aggregated review results
- **LLMReviewer**: Orchestrates AI analysis

Key features:
- Smart pattern extraction from skills.md (only loads relevant patterns)
- Structured prompting for consistent AI responses
- Retry logic with multiple attempts
- Severity-based prioritization (Critical → Info)

#### 3. **Line Number Helper** (`src/line_number_helper.py`)
Utility module for accurate line positioning:
- Parses diff headers (`@@ -old,old_count +new,new_count @@`)
- Maps diff positions to actual file line numbers
- Verifies comment placement accuracy
- Provides line reference tables for debugging

#### 4. **MCP Server** (`src/mcp_server.py`)
Claude Desktop integration:
- Implements Model Context Protocol (MCP)
- Exposes tools for Claude Desktop to invoke
- Handles `review_pr` and `analyze_pr` commands
- Returns structured JSON responses

#### 5. **Main Entry Point** (`src/review_pr.py`)
CLI interface and orchestration:
- Validates environment (GitHub CLI, API keys)
- Filters and adjusts AI-generated comments
- Deduplicates comments by file/line
- Sorts by severity (critical first)
- Posts comments or shows dry-run preview

### Data Flow

```
1. User provides PR URL
        ↓
2. Parse URL → owner/repo/PR#
        ↓
3. Fetch PR metadata + diff (via GitHub CLI)
        ↓
4. Parse diff → Map line numbers
        ↓
5. Load relevant patterns from skills.md
        ↓
6. Send to Claude AI with structured prompt
        ↓
7. Parse AI response → ReviewComment objects
        ↓
8. Filter/validate comments against diff
        ↓
9. Sort by severity + deduplicate
        ↓
10. Post to GitHub (or dry-run preview)
```

### Review Guidelines System

The `skills/skill.md` file contains domain-specific review patterns:

```markdown
## Topics
- Error Handling (1233 patterns)
- External API Design
- Type Safety
- Testing
- Security
- Performance
...
```

**Smart Loading**: The system only loads patterns relevant to the PR:
1. Extracts keywords from PR diff (connector names, struct names, patterns)
2. Scores each pattern by relevance (0-100)
3. Loads top-scoring patterns up to 40,000 char limit
4. Ensures AI receives focused, actionable guidance

### Security Architecture

- **No credentials in code**: API keys loaded from `.env` file (gitignored)
- **Minimal GitHub permissions**: Only requires `repo` scope
- **Local processing**: All code stays local, only API calls go to external services
- **Audit trail**: All actions logged to stdout

## Project Structure

```
ReviewPulse/
├── src/                          # Core source code
│   ├── review_pr.py             # CLI entry point
│   ├── github_client.py         # GitHub API integration
│   ├── llm_reviewer.py          # AI review generation
│   ├── mcp_server.py            # Claude Desktop MCP server
│   └── line_number_helper.py    # Line number utilities
├── skills/
│   └── skill.md                 # Review guidelines database
├── .env.example                 # Environment template
├── .gitignore                   # Git ignore rules
├── requirements.txt             # Python dependencies
├── setup.sh                     # Setup script
├── review_pr.sh                 # Convenience wrapper
├── run_review.sh                # Quick test script
├── claude-desktop-config.json   # MCP configuration template
├── README.md                    # This file
└── SETUP.md                     # Detailed setup guide
```

## Usage

### Basic Commands

```bash
# Dry run (review only, don't post)
python src/review_pr.py https://github.com/owner/repo/pull/123

# Post comments to GitHub
POST_COMMENTS=true python src/review_pr.py <URL>

# Alternative formats
python src/review_pr.py owner/repo#123
python src/review_pr.py owner/repo/pull/123

# Using wrapper script
./review_pr.sh https://github.com/owner/repo/pull/123 --post
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GITHUB_TOKEN` | GitHub Personal Access Token | *required* |
| `ANTHROPIC_API_KEY` | Claude AI API key | *required* |
| `ANTHROPIC_BASE_URL` | Custom API endpoint | anthropic.com |
| `ANTHROPIC_MODEL` | Model selection | claude-3-5-sonnet-20241022 |
| `POST_COMMENTS` | Enable posting to GitHub | false |
| `MAX_COMMENTS` | Maximum comments per review | 30 |
| `SKILLS_PATH` | Path to skill guidelines | ./skills/skill.md |

### Review Severity Levels

| Level | Icon | Description |
|-------|------|-------------|
| Critical | 🔴 | Crashes, data loss, security vulnerabilities |
| High | 🟠 | Functional issues, major bugs |
| Medium | 🟡 | Code quality, potential issues |
| Low | 🟢 | Style, minor suggestions |
| Info | ℹ️ | Documentation, observations |

## Claude Desktop Integration

Configure Claude Desktop to use this as an MCP tool:

1. Open Claude Desktop → Settings → Developer → Edit Config
2. Add the MCP server configuration from `claude-desktop-config.json`
3. Replace paths and API keys with your values
4. Restart Claude Desktop

Now you can ask Claude:
```
Review this PR: https://github.com/owner/repo/pull/123
```

## Customizing Reviews

Edit `skills/skill.md` to add your team's review standards:

```markdown
## Pattern N

### Insight
Description of the pattern/rule

### Example
```language
// Good code example
```

### Anti-pattern
```language
// Bad code example
```
```

Patterns are automatically scored and filtered based on PR content.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "GITHUB_TOKEN not found" | Check `.env` file exists and token is valid |
| "Failed to fetch PR diff" | Verify `gh auth status` and token has `repo` scope |
| "No comments posted" | Set `POST_COMMENTS=true` in `.env` |
| Comments on wrong lines | Check line number mapping in debug output |
| Empty review | Verify API key and check skills.md patterns |

## Development

### Running Tests

```bash
# Activate environment
source venv/bin/activate

# Test line number helper
python -c "from src.line_number_helper import calculate_line_numbers; print('OK')"

# Dry run test
python src/review_pr.py <URL> --dry-run
```

### Adding New Features

1. **New AI Provider**: Extend `LLMReviewer` class with new client
2. **New Review Rules**: Add patterns to `skills/skill.md`
3. **Custom Filters**: Modify `filter_and_adjust_comments()` in `review_pr.py`

## Security Best Practices

- **Never commit `.env` files** (already in `.gitignore`)
- Rotate API keys regularly
- Use GitHub tokens with minimal scopes (`repo` only)
- Review code before enabling `POST_COMMENTS=true`
- Run in dry-run mode first to validate behavior

## License

MIT License - Feel free to modify for your team!

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## Support

For issues and questions:
1. Check [SETUP.md](SETUP.md) for setup help
2. Review this README for usage examples
3. Open an issue on GitHub
