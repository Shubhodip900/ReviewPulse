#!/bin/bash
# Quick test script for PR review
# Usage: ./run_review.sh

set -e
cd "$(dirname "$0")"

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Error: .env file not found. Please create one from .env.example"
    exit 1
fi

# Load environment variables
export $(grep -v '^#' .env | xargs)

# Activate virtual environment
source venv/bin/activate

# Run review (update PR URL as needed)
python src/review_pr.py https://github.com/juspay/hyperswitch-prism/pull/1065 2>&1
