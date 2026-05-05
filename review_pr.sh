#!/bin/bash
# Convenience script to run PR review
# Usage: ./review_pr.sh <PR_URL> [--post]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"

# Check if venv exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Virtual environment not found. Please run setup first:"
    echo "  cd $SCRIPT_DIR && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Check arguments
if [ $# -eq 0 ]; then
    echo "Usage: $0 <PR_URL> [--post]"
    echo ""
    echo "Examples:"
    echo "  $0 https://github.com/owner/repo/pull/123          # Dry run"
    echo "  $0 https://github.com/owner/repo/pull/123 --post   # Post comments"
    echo "  $0 owner/repo#123 --post                           # Short format"
    echo ""
    exit 1
fi

PR_URL="$1"
POST_FLAG=""

if [ "$2" == "--post" ]; then
    export POST_COMMENTS="true"
fi

# Load environment variables
if [ -f "$SCRIPT_DIR/.env" ]; then
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

# Run review
cd "$SCRIPT_DIR"
exec "$VENV_PYTHON" src/review_pr.py "$PR_URL"
