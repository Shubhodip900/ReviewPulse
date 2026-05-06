#!/usr/bin/env python3
"""PR Review Agent - Posts AI code reviews to GitHub PRs."""

import argparse
import os
import sys

from github_client import GitHubClient, DiffParser
from llm_reviewer import LLMReviewer


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════════╗
║                   PR Review Agent v1.0                       ║
╚══════════════════════════════════════════════════════════════╝
""")


def validate_env():
    import subprocess

    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True)
    except:
        print("❌ GitHub CLI required. Install: https://cli.github.com")
        sys.exit(1)

    if not any(
        os.getenv(k)
        for k in ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "JUSPAY_API_KEY"]
    ):
        print("❌ AI API key required (set ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY)")
        sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description="Review a GitHub PR using AI")
    parser.add_argument("pr_url", help="GitHub PR URL")
    parser.add_argument("--dry-run", action="store_true", help="Don't post comments")
    parser.add_argument(
        "--max-comments", type=int, default=30, help="Max comments to post"
    )
    return parser.parse_args()


def normalize_code(text):
    """Normalize code for comparison - remove whitespace, lowercase."""
    return text.strip().lower().replace(" ", "").replace("\t", "")


def filter_and_adjust_comments(comments, diff_parser, max_comments=30):
    """
    Filter and adjust comments to valid changed lines.

    Uses a prioritized approach:
    1. First, try to match by CODE_SNIPPET content (most reliable)
    2. Then try exact line number match
    3. Finally fall back to nearest line within small tolerance
    """
    valid = []
    parsed = diff_parser.parse()

    for c in comments:
        # Handle file path matching (AI might use partial paths)
        actual_file_path = None
        for fp in parsed.keys():
            if c.file_path in fp or fp.endswith(c.file_path.split("/")[-1]):
                actual_file_path = fp
                break

        if not actual_file_path:
            print(f"⚠️  Skipping {c.file_path} - not in diff")
            continue

        # Use the actual full path
        c.file_path = actual_file_path
        changes_map = diff_parser.get_all_changes_map(actual_file_path)
        changed_lines = list(changes_map.keys())

        # PRIORITY 1: Match by CODE_SNIPPET content (most accurate)
        if getattr(c, "code_snippet", None):
            normalized_snippet = normalize_code(c.code_snippet)
            if normalized_snippet:
                best_match_line = None
                best_match_score = 0

                for line_num, content in changes_map.items():
                    normalized_content = normalize_code(content)

                    # Check for substring match in either direction
                    if normalized_snippet in normalized_content:
                        score = len(normalized_snippet)
                    elif normalized_content in normalized_snippet:
                        score = len(normalized_content)
                    else:
                        continue

                    # Prefer matches closer to claimed line number
                    distance = abs(line_num - c.line_number)
                    if distance <= 20:  # Within reasonable range
                        adjusted_score = score - (distance * 0.1)
                    else:
                        adjusted_score = score * 0.5

                    if adjusted_score > best_match_score:
                        best_match_score = adjusted_score
                        best_match_line = line_num

                if best_match_line and best_match_line != c.line_number:
                    print(
                        f"✓ Matched by content: {actual_file_path}:{c.line_number} -> {best_match_line}"
                    )
                    c.line_number = best_match_line
                    valid.append(c)
                    continue

        # PRIORITY 2: Exact line number match
        if c.line_number in changed_lines:
            valid.append(c)
            continue

        # PRIORITY 3: Nearest changed line within small tolerance
        nearest = diff_parser.get_nearest_changed_line(
            actual_file_path, c.line_number, max_distance=3
        )

        if nearest and nearest != c.line_number:
            print(
                f"⚠️  Adjusting {actual_file_path}:{c.line_number} -> {nearest} (nearest changed line)"
            )
            c.line_number = nearest
            valid.append(c)
        else:
            print(
                f"⚠️  Skipping {actual_file_path}:{c.line_number} - not in changed lines"
            )

    # Sort by severity (critical first)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    valid.sort(key=lambda c: severity_order.get(c.severity.lower(), 5))

    # Deduplicate by (file, line)
    seen = set()
    unique = []
    for c in valid:
        key = (c.file_path, c.line_number)
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique[:max_comments]


def main():
    print_banner()
    validate_env()
    args = parse_args()

    print("🔧 Initializing...")
    github = GitHubClient()

    print("   Initializing LLM reviewer...")
    reviewer = LLMReviewer()
    print("   ✓ LLM reviewer initialized")

    # Parse PR
    print(f"🔗 Parsing: {args.pr_url}")
    owner, repo, pr_num = github.parse_pr_url(args.pr_url)
    print(f"   {owner}/{repo}#{pr_num}")

    # Fetch data
    print("\n📥 Fetching PR...")
    pr_info = github.get_pr_info(owner, repo, pr_num)
    pr_diff = github.get_pr_diff(owner, repo, pr_num)
    print(f"   Diff: {len(pr_diff)} chars")

    # Parse diff
    diff_parser = DiffParser(pr_diff)
    files = diff_parser.parse()
    print(f"   Files: {len(files)}")

    # Generate review
    print("\n🤖 Generating review...")
    review = reviewer.generate_review(
        pr_diff, pr_info.get("title", ""), pr_info.get("body", "")
    )
    print(f"   Generated: {len(review.comments)} issues")

    # Filter and adjust comments
    valid_comments = filter_and_adjust_comments(
        review.comments, diff_parser, args.max_comments
    )
    print(f"   Valid comments: {len(valid_comments)}")

    # Dry run
    if args.dry_run or os.getenv("POST_COMMENTS", "false").lower() != "true":
        print("\n🏃 DRY RUN - not posting")
        print("\nComments that would be posted:")
        severity_icons = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢",
            "info": "ℹ️",
        }
        for c in valid_comments:
            icon = severity_icons.get(c.severity.lower(), "🟡")
            print(f"   {icon} {c.file_path}:{c.line_number} ({c.severity})")
            # Print first line of comment
            first_line = c.body.split("\n")[0][:80]
            print(f"      {first_line}...")
        return

    # Post review
    if not valid_comments:
        print("\nℹ️  No valid issues to post")
        return

    print("\n🚀 Posting review...")
    commit_sha = github.get_latest_commit_sha(owner, repo, pr_num)
    print(f"   Commit: {commit_sha[:7]}")

    # Build comment batch
    severity_icons = {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
        "low": "🟢",
        "info": "ℹ️",
    }

    batch = [
        {
            "path": c.file_path,
            "line": c.line_number,
            "body": f"{severity_icons.get(c.severity.lower(), '🟡')} **{c.severity.upper()}**\n\n{c.body}",
        }
        for c in valid_comments
    ]

    result = github.post_review_comments_batch(owner, repo, pr_num, commit_sha, batch)

    if result:
        print("\n✅ Review posted successfully!")
        print(f"   URL: {result.get('html_url', 'N/A')}")
        print("   Review is in PENDING state - submit on GitHub when ready")
    else:
        print("\n⚠️  No review was posted")


if __name__ == "__main__":
    main()
