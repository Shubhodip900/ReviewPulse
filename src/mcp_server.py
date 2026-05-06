#!/usr/bin/env python3
"""
MCP Server for Claude Desktop Integration
Allows Claude Desktop to use the PR Review Agent as a tool.
"""

import os
import sys
import json
from typing import Optional

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from github_client import GitHubClient, DiffParser
from llm_reviewer import LLMReviewer


class MCPHandler:
    """Handle MCP protocol messages."""

    def __init__(self):
        self.github = None
        self.reviewer = None
        self._init_clients()

    def _init_clients(self):
        """Initialize API clients."""
        try:
            self.github = GitHubClient()
            self.reviewer = LLMReviewer()
        except ValueError as e:
            self._send_error(str(e))
            sys.exit(1)

    def _send_response(self, result: dict):
        """Send JSON-RPC response."""
        response = {"jsonrpc": "2.0", "result": result, "id": 1}
        print(json.dumps(response), flush=True)

    def _send_error(self, message: str):
        """Send JSON-RPC error."""
        response = {
            "jsonrpc": "2.0",
            "error": {"code": -32000, "message": message},
            "id": 1
        }
        print(json.dumps(response), flush=True)

    def handle_initialize(self, params: dict) -> dict:
        """Handle initialize request."""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "resources": {}
            },
            "serverInfo": {
                "name": "pr-review-agent",
                "version": "1.0.0"
            }
        }

    def handle_tools_list(self, params: dict) -> dict:
        """List available tools."""
        return {
            "tools": [
                {
                    "name": "review_pr",
                    "description": "Review a GitHub Pull Request and post AI-generated comments",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "pr_url": {
                                "type": "string",
                                "description": "GitHub PR URL (e.g., https://github.com/owner/repo/pull/123 or owner/repo#123)"
                            },
                            "dry_run": {
                                "type": "boolean",
                                "description": "If true, generates review but doesn't post comments",
                                "default": True
                            },
                            "summary_only": {
                                "type": "boolean",
                                "description": "If true, only posts summary without inline comments",
                                "default": False
                            }
                        },
                        "required": ["pr_url"]
                    }
                },
                {
                    "name": "analyze_pr",
                    "description": "Analyze a PR and return review without posting (always dry-run)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "pr_url": {
                                "type": "string",
                                "description": "GitHub PR URL"
                            }
                        },
                        "required": ["pr_url"]
                    }
                }
            ]
        }

    def handle_tools_call(self, params: dict) -> dict:
        """Handle tool invocation."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name == "review_pr":
            return self._review_pr(
                arguments.get("pr_url"),
                arguments.get("dry_run", True),
                arguments.get("summary_only", False)
            )
        elif tool_name == "analyze_pr":
            return self._analyze_pr(arguments.get("pr_url"))
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    def _review_pr(self, pr_url: str, dry_run: bool, summary_only: bool) -> dict:
        """Execute PR review."""
        # Parse PR URL
        owner, repo, pr_number = self.github.parse_pr_url(pr_url)

        # Fetch PR info
        pr_info = self.github.get_pr_info(owner, repo, pr_number)
        pr_title = pr_info.get("title", "")
        pr_description = pr_info.get("body", "")

        # Fetch diff
        pr_diff = self.github.get_pr_diff(owner, repo, pr_number)

        # Generate review
        review = self.reviewer.generate_review(pr_diff, pr_title, pr_description)

        # Format summary
        summary = self._format_summary(review)

        result = {
            "summary": summary,
            "total_comments": len(review.comments),
            "bugs_found": len(review.bugs_found),
            "suggestions": len(review.suggestions),
            "improvements": len(review.improvements),
            "dry_run": dry_run
        }

        if not dry_run:
            # Post comments to GitHub
            commit_sha = self.github.get_latest_commit_sha(owner, repo, pr_number)

            # Post summary
            self.github.post_general_comment(owner, repo, pr_number, summary)

            # Post inline comments if not summary-only
            if not summary_only and review.comments:
                diff_parser = DiffParser(pr_diff)
                valid_comments = self._filter_comments(review.comments, diff_parser)

                if valid_comments:
                    batch_comments = [
                        {
                            "path": c.file_path,
                            "line": c.line_number,
                            "body": f"**[{c.severity.upper()}]** {c.body}",
                            "side": "RIGHT",
                        }
                        for c in valid_comments[:50]  # Limit to 50
                    ]
                    self.github.post_review_comments_batch(
                        owner, repo, pr_number, commit_sha, batch_comments
                    )
                    result["posted_comments"] = len(batch_comments)

        return result

    def _analyze_pr(self, pr_url: str) -> dict:
        """Analyze PR without posting (always dry-run)."""
        return self._review_pr(pr_url, dry_run=True, summary_only=False)

    def _format_summary(self, review) -> str:
        """Format review summary."""
        lines = ["## AI Code Review", ""]
        lines.append("### Summary")
        lines.append(review.summary)
        lines.append("")

        if review.bugs_found:
            lines.append("### Bugs Found")
            for i, bug in enumerate(review.bugs_found, 1):
                lines.append(f"{i}. {bug}")
            lines.append("")

        if review.suggestions:
            lines.append("### Suggestions")
            for i, suggestion in enumerate(review.suggestions, 1):
                lines.append(f"{i}. {suggestion}")
            lines.append("")

        if review.improvements:
            lines.append("### Improvements")
            for i, improvement in enumerate(review.improvements, 1):
                lines.append(f"{i}. {improvement}")
            lines.append("")

        lines.append("---")
        lines.append("*Generated by PR Review Agent*")

        return "\n".join(lines)

    def _filter_comments(self, comments, diff_parser):
        """Filter comments to only valid changed lines."""
        parsed_files = diff_parser.parse()
        valid = []

        for comment in comments:
            if comment.file_path not in parsed_files:
                continue
            changed_lines = [c["line_number"] for c in parsed_files[comment.file_path]["changes"]]
            if comment.line_number in changed_lines:
                valid.append(comment)

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        valid.sort(key=lambda c: severity_order.get(c.severity, 5))

        return valid


def main():
    """Main MCP server loop."""
    handler = MCPHandler()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
            method = message.get("method")
            params = message.get("params", {})

            if method == "initialize":
                result = handler.handle_initialize(params)
            elif method == "tools/list":
                result = handler.handle_tools_list(params)
            elif method == "tools/call":
                result = handler.handle_tools_call(params)
            else:
                result = {"error": f"Unknown method: {method}"}

            response = {
                "jsonrpc": "2.0",
                "result": result,
                "id": message.get("id")
            }
            print(json.dumps(response), flush=True)

        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": str(e)},
                "id": message.get("id", 1)
            }
            print(json.dumps(error_response), flush=True)


if __name__ == "__main__":
    main()
