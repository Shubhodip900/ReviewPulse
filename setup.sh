#!/bin/bash
# Setup script for PR Review Agent

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Setting up PR Review Agent..."
echo "Location: $SCRIPT_DIR"
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version || { echo "Python 3 is required"; exit 1; }

# Create virtual environment
echo "Creating virtual environment..."
cd "$SCRIPT_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activate and install dependencies
echo "Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Copy .env.template to .env:"
echo "   cp .env.template .env"
echo ""
echo "2. Edit .env and add your API keys:"
echo "   - GITHUB_TOKEN (from https://github.com/settings/tokens)"
echo "   - ANTHROPIC_API_KEY (from https://console.anthropic.com/)"
echo ""
echo "3. Test with a dry run:"
echo "   ./review_pr.sh <PR_URL>"
echo ""
echo "4. To post comments, use --post flag or set POST_COMMENTS=true:"
echo "   ./review_pr.sh <PR_URL> --post"
echo ""
