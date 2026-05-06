"""
Helper module to provide accurate line number mappings for diffs.
This pre-calculates line numbers to help the AI place comments accurately.
"""

import re
from typing import Dict, List, Tuple, Optional


def calculate_line_numbers(
    diff_text: str, target_file: str = None
) -> Dict[str, Dict[int, str]]:
    """
    Calculate exact line numbers for all added lines in a diff.

    Returns a dict mapping file_path -> {line_number: content}
    """
    files = {}
    current_file = None
    line_number_new = 0

    for line in diff_text.split("\n"):
        if line.startswith("diff --git"):
            if current_file and current_file["path"]:
                files[current_file["path"]] = current_file
            current_file = {
                "path": None,
                "changes": {},  # line_number -> content
            }

        elif line.startswith("+++ b/"):
            if current_file:
                current_file["path"] = line[6:]

        elif line.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if match:
                _, _, new_start, _ = match.groups()
                line_number_new = int(new_start) - 1

        elif line.startswith("+") and not line.startswith("+++"):
            line_number_new += 1
            if current_file:
                current_file["changes"][line_number_new] = line[1:]

        elif line and not line.startswith("\\") and not line.startswith("-"):
            # Context line (space prefix) - counts toward new file line number
            if not line.startswith("@@"):
                line_number_new += 1

    if current_file and current_file["path"]:
        files[current_file["path"]] = current_file

    # Filter to target file if specified
    if target_file:
        return {k: v for k, v in files.items() if target_file in k}

    return files


def find_potential_issues(diff_text: str) -> List[Tuple[str, int, str, str]]:
    """
    Find potential code issues in the diff and return their exact line numbers.

    Returns list of (file_path, line_number, issue_type, content)
    """
    issues = []
    line_map = calculate_line_numbers(diff_text)

    # Patterns to look for
    patterns = [
        (r"\.unwrap\(\)", "UNWRAP"),
        (r"\.expect\(", "EXPECT"),
        (r"#\[derive\(.*Default", "DEFAULT_DERIVE"),
        (r"unwrap_or_default\(\)", "UNWRAP_OR_DEFAULT"),
    ]

    for file_path, changes in line_map.items():
        for line_num, content in changes.items():
            for pattern, issue_type in patterns:
                if re.search(pattern, content):
                    issues.append((file_path, line_num, issue_type, content))

    return issues


def format_line_reference_table(diff_text: str, max_entries: int = 100) -> str:
    """
    Format a reference table of line numbers for the AI to use.

    This provides a lookup table that the AI can use to verify its line numbers.
    """
    files = calculate_line_numbers(diff_text)

    lines = ["# LINE NUMBER REFERENCE TABLE", ""]
    lines.append("Use this table to verify your line numbers are correct:")
    lines.append("")

    for file_path, changes in files.items():
        lines.append(f"## File: {file_path}")
        lines.append("")
        lines.append("| Line | Content Preview |")
        lines.append("|------|----------------|")

        # Sort by line number and take first max_entries
        sorted_changes = sorted(changes.items())[:max_entries]
        for line_num, content in sorted_changes:
            preview = content[:60].replace("|", "\\|")
            lines.append(f"| {line_num} | {preview} |")

        if len(changes) > max_entries:
            lines.append(f"| ... | ({len(changes) - max_entries} more lines) |")

        lines.append("")

    return "\n".join(lines)


def verify_line_number(
    diff_text: str, file_path: str, claimed_line: int, content_hint: str = None
) -> Optional[int]:
    """
    Verify if a claimed line number is valid for a file.

    If content_hint is provided, also verify the content matches.
    Returns the corrected line number or None if not found.
    """
    files = calculate_line_numbers(diff_text)

    # Find matching file (partial match)
    matching_file = None
    for fp in files.keys():
        if file_path in fp or fp.endswith(file_path.split("/")[-1]):
            matching_file = fp
            break

    if not matching_file:
        return None

    changes = files[matching_file]

    # Check if claimed line exists
    if claimed_line in changes:
        if content_hint:
            actual_content = changes[claimed_line]
            # Normalize for comparison
            actual_norm = actual_content.strip().lower().replace(" ", "")
            hint_norm = content_hint.strip().lower().replace(" ", "")

            if hint_norm in actual_norm or actual_norm in hint_norm:
                return claimed_line
        else:
            return claimed_line

    # Try to find nearby line with similar content
    if content_hint:
        hint_norm = content_hint.strip().lower().replace(" ", "")
        for line_num, content in sorted(changes.items()):
            actual_norm = content.strip().lower().replace(" ", "")
            if hint_norm in actual_norm or actual_norm in hint_norm:
                return line_num

    return None
