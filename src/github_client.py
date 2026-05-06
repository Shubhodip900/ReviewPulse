"""
GitHub API Client for PR Review Agent
Uses GitHub CLI (gh) for all operations.
"""

import json
import re
import subprocess
from typing import Dict, List, Optional, Tuple


class GitHubClient:
    """Client for interacting with GitHub using gh CLI."""

    def __init__(self, token: Optional[str] = None):
        """Initialize - uses gh CLI for auth."""
        self._check_gh_cli()

    def _check_gh_cli(self):
        """Verify gh CLI is installed and authenticated."""
        try:
            subprocess.run(["gh", "auth", "status"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("GitHub CLI not authenticated. Run: gh auth login")

    def _gh_api(
        self, endpoint: str, method: str = "GET", data: Optional[Dict] = None
    ) -> Dict:
        """Make an API call using gh cli."""
        cmd = ["gh", "api", endpoint, "--method", method]
        if data:
            cmd.extend(["--input", "-"])
            input_data = json.dumps(data)
        else:
            input_data = None

        result = subprocess.run(cmd, input=input_data, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"gh CLI error: {result.stderr}")

        if result.stdout:
            return json.loads(result.stdout)
        return {}

    def parse_pr_url(self, pr_url: str) -> Tuple[str, str, int]:
        """Parse a GitHub PR URL."""
        pr_url = pr_url.strip()
        if "github.com" in pr_url:
            pattern = r"github\.com/([^/]+)/([^/]+)/pull/(\d+)"
        elif "#" in pr_url:
            pattern = r"([^/]+)/([^#]+)#(\d+)"
        else:
            pattern = r"([^/]+)/([^/]+)/pull/(\d+)"

        match = re.search(pattern, pr_url)
        if not match:
            raise ValueError(f"Invalid PR URL: {pr_url}")

        owner, repo, pr_number = match.groups()
        return owner, repo.replace(".git", ""), int(pr_number)

    def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Fetch PR diff."""
        result = subprocess.run(
            ["gh", "pr", "diff", str(pr_number), "--repo", f"{owner}/{repo}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return result.stdout

    def get_pr_info(self, owner: str, repo: str, pr_number: int) -> Dict:
        """Fetch PR metadata."""
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                f"{owner}/{repo}",
                "--json",
                "title,body,state,headRefOid,headRefName,baseRefName",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def get_pr_files(self, owner: str, repo: str, pr_number: int) -> List[Dict]:
        """Fetch list of changed files in PR."""
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                f"{owner}/{repo}",
                "--json",
                "files",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        return data.get("files", [])

    def get_latest_commit_sha(self, owner: str, repo: str, pr_number: int) -> str:
        """Get latest commit SHA."""
        info = self.get_pr_info(owner, repo, pr_number)
        return info.get("headRefOid", "")

    def _submit_existing_review(
        self, owner: str, repo: str, pr_number: int, review_id: int
    ) -> bool:
        """Submit an existing pending review to clear it."""
        try:
            endpoint = (
                f"repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id}/events"
            )
            self._gh_api(
                endpoint,
                method="POST",
                data={"event": "SUBMIT", "body": "Previous review submitted by bot"},
            )
            print(f"   ✓ Submitted existing review #{review_id}")
            return True
        except Exception as e:
            print(f"   ⚠️  Could not submit review #{review_id}: {e}")
            return False

    def _delete_existing_review(
        self, owner: str, repo: str, pr_number: int, review_id: int
    ) -> bool:
        """Delete a pending review."""
        try:
            endpoint = f"repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id}"
            self._gh_api(endpoint, method="DELETE")
            print(f"   ✓ Deleted existing review #{review_id}")
            return True
        except Exception as e:
            print(f"   ⚠️  Could not delete review #{review_id}: {e}")
            return False

    def _add_comments_to_existing_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        review_id: int,
        comments: List[Dict],
    ) -> bool:
        """Add comments to an existing pending review."""
        try:
            for c in comments:
                comment_data = {
                    "path": c["path"],
                    "line": c["line"],
                    "side": "RIGHT",
                    "body": c["body"],
                }
                endpoint = f"repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id}/comments"
                self._gh_api(endpoint, method="POST", data=comment_data)
            return True
        except Exception as e:
            print(f"   Warning: Could not add comments to existing review: {e}")
            return False

    def post_review_comments_batch(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_id: str,
        comments: List[Dict],
    ) -> Dict:
        """Post all comments as a single review."""
        if not comments:
            print("   No comments to post")
            return {}

        print(f"   Creating review with {len(comments)} comments...")

        # Build comments array - deduplicate by path+line
        seen = set()
        comments_json = []
        skipped = 0

        for c in comments:
            key = (c["path"], c["line"])
            if key in seen:
                print(f"   ⚠️  Skipping duplicate comment on {c['path']}:{c['line']}")
                skipped += 1
                continue
            seen.add(key)

            comments_json.append(
                {
                    "path": c["path"],
                    "line": c["line"],
                    "side": "RIGHT",
                    "body": c["body"],
                }
            )

        if skipped:
            print(f"   Skipped {skipped} duplicate comments")

        if not comments_json:
            print("   No valid comments to post after deduplication")
            return {}

        # Check for existing pending reviews and submit them first
        # (GitHub only allows one pending review per user per PR)
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}/reviews"],
                capture_output=True,
                text=True,
                check=True,
            )
            reviews = json.loads(result.stdout)

            for review in reviews:
                if review.get("state") == "PENDING":
                    review_id = review.get("id")
                    print(
                        f"   Found existing pending review #{review_id}, submitting it first..."
                    )
                    # Submit with CHANGES_REQUESTED to clear it
                    try:
                        self._gh_api(
                            f"repos/{owner}/{repo}/pulls/{pr_number}/reviews/{review_id}/events",
                            method="POST",
                            data={
                                "event": "CHANGES_REQUESTED",
                                "body": "Previous review - more comments coming",
                            },
                        )
                        print(f"   ✓ Submitted existing review #{review_id}")
                    except Exception as e:
                        print(f"   ⚠️  Could not submit review #{review_id}: {e}")
                        # Continue anyway - try to create new review
        except Exception as e:
            print(f"   Warning: Could not check existing reviews: {e}")

        # Create the review with comments
        review_data = {
            "commit_id": commit_id,
            "comments": comments_json,
        }

        endpoint = f"repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        result = self._gh_api(endpoint, method="POST", data=review_data)

        url = result.get("html_url", "")
        print(f"   ✓ Created pending review: {url}")
        print(f"   ⚠️  Review is PENDING - submit on GitHub when ready")

        return result


class DiffParser:
    """Parse GitHub PR diff."""

    def __init__(self, diff_text: str):
        self.diff_text = diff_text
        self.files = {}

    def parse(self) -> Dict[str, Dict]:
        """Parse diff and return file changes with hunk information."""
        current_file = None
        line_number_new = 0
        current_hunk_start = 0

        for line in self.diff_text.split("\n"):
            if line.startswith("diff --git"):
                if current_file:
                    self.files[current_file["path"]] = current_file
                current_file = {
                    "path": None,
                    "changes": [],
                    "additions": 0,
                    "deletions": 0,
                }

            elif line.startswith("+++ b/"):
                current_file["path"] = line[6:]

            elif line.startswith("@@"):
                match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
                if match:
                    _, _, new_start, _ = match.groups()
                    line_number_new = int(new_start) - 1
                    current_hunk_start = int(new_start)

            elif line.startswith("+") and not line.startswith("+++"):
                line_number_new += 1
                if current_file:
                    current_file["changes"].append(
                        {
                            "type": "addition",
                            "line_number": line_number_new,
                            "content": line[1:],
                            "hunk_start": current_hunk_start,
                        }
                    )
                    current_file["additions"] += 1

            elif line.startswith("-") and not line.startswith("---"):
                if current_file:
                    current_file["deletions"] += 1

            elif line and not line.startswith("\\"):
                line_number_new += 1

        if current_file and current_file["path"]:
            self.files[current_file["path"]] = current_file

        return self.files

    def get_changed_lines(self, file_path: str) -> List[int]:
        """Get list of added line numbers."""
        if file_path not in self.files:
            return []
        return [c["line_number"] for c in self.files[file_path]["changes"]]

    def get_nearest_changed_line(
        self, file_path: str, target_line: int, max_distance: int = 5
    ) -> Optional[int]:
        """Find the nearest changed line to the target line."""
        if file_path not in self.files:
            return None

        changed_lines = self.get_changed_lines(file_path)
        if not changed_lines:
            return None

        if target_line in changed_lines:
            return target_line

        nearest = None
        min_dist = float("inf")

        for line in changed_lines:
            dist = abs(line - target_line)
            if dist <= max_distance and dist < min_dist:
                min_dist = dist
                nearest = line

        return nearest

    def get_line_content(self, file_path: str, line_number: int) -> Optional[str]:
        """Get the content of a specific added line by its line number."""
        if file_path not in self.files:
            return None

        for change in self.files[file_path]["changes"]:
            if change["line_number"] == line_number:
                return change["content"]

        return None

    def get_all_changes_map(self, file_path: str) -> Dict[int, str]:
        """Get a map of line number -> content for all changes in a file."""
        if file_path not in self.files:
            return {}

        return {
            c["line_number"]: c["content"] for c in self.files[file_path]["changes"]
        }

    def find_line_by_content(
        self,
        file_path: str,
        content_hint: str,
        near_line: int = None,
        max_distance: int = 5,
    ) -> Optional[int]:
        """Find a line by searching for content similarity.

        This helps when line numbers are slightly off but the content reference is known.
        Searches for lines containing the content hint near the expected line.
        """
        if file_path not in self.files:
            return None

        # Normalize the content hint for comparison
        hint_normalized = content_hint.strip().lower().replace(" ", "")
        if not hint_normalized:
            return None

        candidates = []

        for change in self.files[file_path]["changes"]:
            line_num = change["line_number"]
            content = change["content"]
            content_normalized = content.strip().lower().replace(" ", "")

            # Check if hint is contained in content or vice versa
            if (
                hint_normalized in content_normalized
                or content_normalized in hint_normalized
            ):
                distance = abs(line_num - near_line) if near_line else 0
                candidates.append((distance, line_num, content))

        if not candidates:
            return None

        # Prefer candidates closer to the expected line number
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
