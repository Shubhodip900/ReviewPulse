"""
LLM Review Generator for PR Review Agent
Uses Anthropic's Claude API to generate code reviews.
"""

import os
import re
from typing import Dict, List, Optional
from dataclasses import dataclass
import anthropic
from line_number_helper import calculate_line_numbers, verify_line_number


@dataclass
class ReviewComment:
    """Represents a single review comment."""

    file_path: str
    line_number: int
    body: str
    severity: str = "medium"
    code_snippet: str = ""  # The actual code at the claimed line


@dataclass
class ReviewSummary:
    """Complete review output."""

    summary: str
    comments: List[ReviewComment]
    suggestions: List[str]
    bugs_found: List[str]
    improvements: List[str]


class LLMReviewer:
    """Generates code reviews using Claude API."""

    def __init__(
        self, api_key: Optional[str] = None, skills_path: Optional[str] = None
    ):
        """Initialize with API key and path to skills file."""
        self.api_key = (
            api_key
            or os.getenv("ANTHROPIC_AUTH_TOKEN")
            or os.getenv("JUSPAY_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
        )
        if not self.api_key:
            raise ValueError("API key required")

        base_url = os.getenv("ANTHROPIC_BASE_URL")
        self.model = os.getenv("ANTHROPIC_MODEL") or os.getenv(
            "CLAUDE_MODEL", "claude-sonnet-4-6"
        )

        if base_url:
            self.client = anthropic.Anthropic(api_key=self.api_key, base_url=base_url)
            print(f"   Using custom endpoint: {base_url}")
        else:
            self.client = anthropic.Anthropic(api_key=self.api_key)

        print(f"   Model: {self.model}")

        self.skills_path = skills_path or os.path.join(
            os.path.dirname(__file__), "..", "skills", "skill.md"
        )
        self.skills_content = self._load_skills()

    def _load_skills(self) -> str:
        """Load the skills markdown file."""
        try:
            with open(self.skills_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def generate_review(
        self, pr_diff: str, pr_title: str = "", pr_description: str = ""
    ) -> ReviewSummary:
        """Generate a code review with retry logic."""
        max_retries = 3
        import httpx

        for attempt in range(max_retries):
            print(f"   Attempt {attempt + 1}/{max_retries}...")

            system_prompt = self._build_system_prompt(pr_diff)
            user_prompt = self._build_user_prompt(pr_diff, pr_title, pr_description)

            http_client = None
            try:
                http_client = httpx.Client(timeout=300.0)
                base_url = os.getenv("ANTHROPIC_BASE_URL")

                if base_url:
                    client = anthropic.Anthropic(
                        api_key=self.api_key, base_url=base_url, http_client=http_client
                    )
                else:
                    client = anthropic.Anthropic(
                        api_key=self.api_key, http_client=http_client
                    )

                response = client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    temperature=0.1,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )

                review_text = None
                for content_block in response.content:
                    if hasattr(content_block, "text"):
                        review_text = content_block.text
                        break

                if review_text is None:
                    raise ValueError("No text content in response")

                review = self._parse_review_response(review_text)

                if len(review.comments) >= 1:
                    print(f"   ✓ Found {len(review.comments)} issues")
                    return review
                else:
                    print(f"   ⚠️  Found 0 issues, retrying...")

            except Exception as e:
                print(f"   ⚠️  Error: {e}")
                continue
            finally:
                try:
                    if http_client:
                        http_client.close()
                except:
                    pass

        print(f"   ⚠️  Max retries reached")
        return ReviewSummary(
            summary="", comments=[], suggestions=[], bugs_found=[], improvements=[]
        )

    def _extract_relevant_patterns(self, pr_diff: str = "") -> str:
        """
        Extract relevant patterns from skills based on the PR content.

        Instead of taking a fixed character chunk, we:
        1. Parse all patterns from skills.md
        2. Score them by relevance to the PR content
        3. Return the most relevant patterns up to a token limit
        """
        if not self.skills_content:
            return ""

        # Keywords from the PR diff to match against
        pr_keywords = set()
        if pr_diff:
            # Extract connector names (e.g., deutschebank, stripe, adyen)
            connector_matches = re.findall(
                r"\b([a-z]+[a-z0-9]*)[Cc]onnector|[Cc]onnector::([A-Z][a-zA-Z]+)",
                pr_diff,
            )
            for m in connector_matches:
                pr_keywords.add(m[0].lower() if m[0] else m[1].lower())

            # Extract struct/trait names
            struct_matches = re.findall(r"struct\s+(\w+)|impl.*for\s+(\w+)", pr_diff)
            for m in struct_matches:
                pr_keywords.add(m[0] if m[0] else m[1])

            # Generic rust patterns
            generic_patterns = [
                "unwrap",
                "expect",
                "unwrap_or_default",
                "match",
                "Result",
                "Option",
                "Error",
                "Default",
                "Clone",
            ]
            for p in generic_patterns:
                if p in pr_diff:
                    pr_keywords.add(p.lower())

        # Parse patterns from skills
        # Pattern format: ## Pattern N followed by ### Insight, ### Example, etc.
        pattern_blocks = re.split(r"\n## Pattern \d+\s*\n", self.skills_content)

        scored_patterns = []
        for block in pattern_blocks:
            if not block.strip():
                continue

            # Calculate relevance score
            score = 0
            block_lower = block.lower()

            # Generic high-value patterns (always include)
            generic_indicators = [
                "unwrap",
                "expect",
                "unwrap_or_default",
                "#[derive(default)]",
                "webhook",
                "signature",
                "missing required field",
                "not supported",
                "notimplemented",
                "todo!",
                "status mapping",
                "url pattern",
                "endpoint",
            ]
            for indicator in generic_indicators:
                if indicator in block_lower:
                    score += 10

            # Connector-generic patterns
            if "other connectors" in block_lower or "connector" in block_lower:
                score += 15

            # PR-specific relevance
            for keyword in pr_keywords:
                if keyword and len(keyword) > 2 and keyword in block_lower:
                    score += 20

            # Boost patterns with clear fixes/examples
            if "### Example" in block or "**Fix:**" in block:
                score += 5

            scored_patterns.append((score, block))

        # Sort by score (descending) and select top patterns
        scored_patterns.sort(key=lambda x: x[0], reverse=True)

        # Build excerpt up to ~40000 chars (twice the original limit)
        excerpts = []
        total_len = 0
        max_len = 40000

        # Always include highest scoring patterns
        for score, block in scored_patterns[:50]:  # Top 50 patterns
            if total_len + len(block) > max_len:
                break
            if score > 0:  # Only include if somewhat relevant
                excerpts.append(block)
                total_len += len(block)

        # If we have room, add some generic patterns for coverage
        if total_len < max_len * 0.8:
            for score, block in scored_patterns[50:]:
                if total_len + len(block) > max_len:
                    break
                # Include patterns that mention common issues
                if any(
                    x in block.lower()
                    for x in ["unwrap", "expect", "default", "error handling"]
                ):
                    excerpts.append(block)
                    total_len += len(block)

        return "\n---\n".join(excerpts)

    def _build_system_prompt(self, pr_diff: str = "") -> str:
        """Build the system prompt with skills and patterns."""
        # Extract relevant patterns based on PR content
        skills_excerpt = self._extract_relevant_patterns(pr_diff)

        return f"""You are a senior Rust code reviewer for a payments processing system. Find bugs in PR diffs.

# CODE REVIEW PATTERNS FROM PAST REVIEWS

{skills_excerpt}

---

# YOUR TASK

Analyze the PR diff and find concrete bugs and issues.

## SEVERITY LEVELS
- CRITICAL: Crash, data loss, security vulnerability, incorrect payment amount
- HIGH: Logic error, missing error handling, wrong API endpoint, status mapping bug
- MEDIUM: Code quality, unnecessary clone, hardcoded value, missing validation
- LOW: Style, minor suggestion, documentation

## FOCUS ON THESE BUG PATTERNS
1. unwrap/expect that could panic
2. unwrap_or_default hiding errors
3. Wrong URL routing (using capture URL for authorize, etc.)
4. Incorrect status mapping
5. Missing required fields in request structs
6. Amount/currency conversion errors
7. Wrong error handling (Ok(false) instead of Err)
8. Dead code or unreachable match arms
9. Mandatory fields with Default derive (creates invalid state)
10. Type mismatches in response handling

## WRITING CONNECTOR-SPECIFIC COMMENTS

The patterns above are from past reviews. When applying them:

1. **Be Specific**: Comment on THIS connector's code, not generic patterns
   - BAD: "URLs should use /services/v2.1/ pattern for consistency"
   - GOOD: "Deutschebank's Capture flow uses /payments/{id}/captures but their API docs specify /services/v2.1/payment/..."

2. **Check the Actual API**: Don't assume patterns from Stripe/Adyen/etc. apply
   - Look at the actual URL patterns in the diff
   - Verify against the connector's implementation logic

3. **Report Real Issues Only**: Don't flag code that follows the connector's actual patterns
   - If Deutschebank uses /payments/{id} (not /services/v2.1/...), that's their API design
   - Only flag if the code contradicts ITSELF or uses clearly wrong patterns

4. **Technical Accuracy**: Explain the actual technical problem
   - WHY is this wrong? (panic risk, API mismatch, logic error)
   - WHAT should change? (specific fix, not vague "fix this")

## LINE NUMBER CALCULATION - CRITICAL - READ CAREFULLY

The diff shows lines with @@ headers: @@ -old_line,old_count +new_line,new_count @@

The +NUMBER after @@ is the STARTING line number for NEW code (lines with +).

COUNTING RULE:
1. The first + line after @@ has line number = +NUMBER from the header
2. Each subsequent + line increments by 1
3. CONTEXT lines (no +/- prefix) also increment the counter

Example:
```
@@ -100,5 +2596,10 @@
+// Comment here      <- Line 2596 (FIRST + line = +2596)
+#[derive(Default)]   <- Line 2597 (+2596 + 1)
 pub struct Foo {{    <- Line 2598 (context line, continues counting)
+    bar: String,     <- Line 2599 (+2598 + 1)
     old_field: i32,  <- Line 2600 (context line)
```

IMPORTANT:
- Count EVERY line shown in the diff, not just + lines
- Context lines (space prefix) are part of the sequence
- The actual file line number includes ALL lines, not just additions

## RESPONSE FORMAT

For EACH issue, output EXACTLY:

FILE: <exact file path>
LINE: <EXACT line number>
SEVERITY: <CRITICAL|HIGH|MEDIUM|LOW>
COMMENT: <detailed technical explanation>
CODE_SNIPPET: <the actual line of code with the issue>
---

CRITICAL RULES:
1. Find 5-15 real issues in added lines (+ lines)
2. Line numbers MUST be EXACT - trace from @@ header carefully
3. Include CODE_SNIPPET showing the actual code at that line
4. Put comment on the EXACT line where the bug occurs
5. Each issue ends with ---
6. No narrative text outside issue blocks"""

    def _build_user_prompt(
        self, pr_diff: str, pr_title: str, pr_description: str
    ) -> str:
        """Build the user prompt with the PR context."""
        parts = []

        if pr_title:
            parts.append(f"PR TITLE: {pr_title}")
        if pr_description:
            desc = pr_description[:800] if len(pr_description) > 800 else pr_description
            parts.append(f"PR DESCRIPTION:\n{desc}")

        parts.append("""REVIEW INSTRUCTIONS:

STEP 1: UNDERSTAND LINE NUMBERING
The diff @@ header shows: @@ -old_start,old_count +new_start,new_count @@

+new_start = the line number of the FIRST + line in the diff hunk.

COUNTING METHOD:
- Start at +new_start for the first + line
- Increment by 1 for EVERY line shown in the diff (including context lines starting with space)
- BOTH added lines (+) AND context lines contribute to line count

EXAMPLE - Trace carefully:
@@ -100,5 +2596,15 @@
+pub mod transformers;           <- Line 2596 (+2596 is first added line)
+use crate::...;                 <- Line 2597 (+2596 + 1)
+use std::fmt::Debug;            <- Line 2598 (+2597 + 1)
+
+use common_enums::...;          <- Line 2600 (+2599 + 1 for empty line)
 pub enum CurrencyUnit {{         <- Line 2601 (context line, no +/-)
+    MinorUnit,                  <- Line 2602 (added after context)

STEP 2: ANALYZE THE CONNECTOR-SPECIFIC CODE
This PR introduces a new connector integration. Focus on:

1. **URL Endpoint Patterns**: Does the connector use consistent API paths?
   - Check if base URL patterns match the connector's actual API
   - Verify endpoint paths follow the connector's documentation

2. **Request/Response Structs**: Are the data structures correct?
   - Check for mandatory fields with `#[derive(Default)]` - this creates invalid states
   - Verify field types match the connector API spec
   - Look for missing error handling in deserialization

3. **Error Handling**: Is error propagation correct?
   - `unwrap()` or `expect()` on optional fields will panic
   - Missing error variants for connector-specific failures
   - Incorrect error mapping (returning Ok(false) instead of Err)

4. **Status Mapping**: Are payment/refund statuses mapped correctly?
   - Each connector has unique status strings
   - Missing status variants cause silent failures

5. **Authentication**: Is auth handling secure?
   - Credentials exposed in logs/errors
   - Missing auth header validation

STEP 3: VERIFY YOUR LINE NUMBER
After calculating the line number:
1. Look at the actual line of code at that position
2. Include that exact code in CODE_SNIPPET field
3. Verify the comment applies to that specific line

STEP 4: WRITE CONNECTOR-SPECIFIC COMMENTS
- Reference the actual connector name (not "other connectors")
- Explain WHY this is wrong for THIS connector specifically
- Suggest the fix based on the connector's API patterns

For each bug found, report:
- FILE: exact path from diff
- LINE: calculated line number
- SEVERITY: CRITICAL/HIGH/MEDIUM/LOW
- COMMENT: specific technical explanation for this connector
- CODE_SNIPPET: the actual code at that line

DIFF TO REVIEW:""")

        # Truncate diff if too long
        max_diff = 80000
        diff_to_send = pr_diff[:max_diff] if len(pr_diff) > max_diff else pr_diff
        if len(pr_diff) > max_diff:
            parts.append(f"(truncated from {len(pr_diff)} chars)")

        parts.append(f"```diff\n{diff_to_send}\n```")
        parts.append(
            """\nFind issues. Format:
FILE: path
LINE: EXACT_LINE_NUMBER
SEVERITY: HIGH
COMMENT: explanation
CODE_SNIPPET: the exact code at that line
---"""
        )

        return "\n\n".join(parts)

    def _parse_review_response(self, response: str) -> ReviewSummary:
        """Parse the LLM response into structured ReviewSummary."""
        comments = []

        # Split response by --- separators
        issue_blocks = response.split("\n---")

        for block in issue_blocks:
            block = block.strip()
            if not block:
                continue

            # Extract fields from each block
            file_path = self._extract_field(block, "FILE")
            line_str = self._extract_field(block, "LINE")
            severity = self._extract_field(block, "SEVERITY")
            comment = self._extract_field(block, "COMMENT")
            code_snippet = self._extract_field(block, "CODE_SNIPPET")

            if not file_path or not line_str:
                continue

            try:
                line_number = int(line_str)

                # Normalize severity
                severity_norm = severity.lower() if severity else "medium"
                if severity_norm not in ["critical", "high", "medium", "low"]:
                    severity_norm = "medium"

                # Clean up comment
                if comment:
                    comment = re.sub(r"\n+", "\n", comment).strip()

                comments.append(
                    ReviewComment(
                        file_path=file_path,
                        line_number=line_number,
                        body=comment or "Issue identified",
                        severity=severity_norm,
                        code_snippet=code_snippet or "",
                    )
                )
            except (ValueError, IndexError):
                continue

        # If parsing didn't work, try fallback
        if not comments:
            comments = self._fallback_parse(response)

        return ReviewSummary(
            summary=f"Found {len(comments)} issues",
            comments=comments,
            suggestions=[],
            bugs_found=[],
            improvements=[],
        )

    def _extract_field(self, text: str, field_name: str) -> str:
        """Extract a field value from text."""
        pattern = rf"{field_name}:\s*(.+?)(?=\n[A-Z_]+:|\Z)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    def _fallback_parse(self, response: str) -> List[ReviewComment]:
        """Fallback parsing if regex fails."""
        comments = []
        lines = response.split("\n")

        current = {}
        for line in lines:
            line = line.strip()

            if line.startswith("FILE:"):
                if (
                    current.get("file")
                    and current.get("line")
                    and current.get("comment")
                ):
                    try:
                        comments.append(
                            ReviewComment(
                                file_path=current["file"],
                                line_number=int(current["line"]),
                                body=current["comment"],
                                severity=current.get("severity", "medium").lower(),
                            )
                        )
                    except:
                        pass
                current = {"file": line[5:].strip()}
            elif line.startswith("LINE:"):
                current["line"] = line[5:].strip()
            elif line.startswith("SEVERITY:"):
                sev = line[9:].strip().lower()
                current["severity"] = (
                    sev if sev in ["critical", "high", "medium", "low"] else "medium"
                )
            elif line.startswith("COMMENT:"):
                current["comment"] = line[8:].strip()
            elif "comment" in current and line and not line.startswith("---"):
                current["comment"] += "\n" + line

        # Don't forget the last one
        if current.get("file") and current.get("line") and current.get("comment"):
            try:
                comments.append(
                    ReviewComment(
                        file_path=current["file"],
                        line_number=int(current["line"]),
                        body=current["comment"],
                        severity=current.get("severity", "medium"),
                    )
                )
            except:
                pass

        return comments
