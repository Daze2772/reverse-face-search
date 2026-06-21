#!/usr/bin/env bash
# Reverse Face Search — Quick Launch Script
# Usage: ./launch.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "Error: Virtual environment not found. Run: python3.11 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Create directories
mkdir -p uploads logs dossiers

# Ensure Playwright browsers are installed
if ! python -c "from playwright.sync_api import sync_playwright; sync_playwright().start().chromium.launch()" 2>/dev/null; then
    echo "Installing Playwright browsers..."
    playwright install chromium
fi

echo "Starting Reverse Face Search server..."
echo "Dashboard: http://127.0.0.1:8000"
echo ""

python -m src.main
