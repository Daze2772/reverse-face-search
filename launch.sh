#!/usr/bin/env bash
# Reverse Face Search v2 — Quick Launch Script
# Usage: ./launch.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# .env check
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo "No .env found; copying .env.example → .env. Edit it to add your API keys."
        cp .env.example .env
    fi
fi

# Activate virtual environment if present
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# Create writable dirs
mkdir -p uploads logs dossiers data cache reports

# Playwright Chromium check
if ! python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop()" >/dev/null 2>&1; then
    echo "Installing Playwright Chromium..."
    python -m playwright install chromium
fi

echo "Starting Reverse Face Search v2 server..."
echo "Dashboard: http://127.0.0.1:8000"
echo ""
exec python -m src.main
