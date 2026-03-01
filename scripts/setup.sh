#!/usr/bin/env bash
# VowCut macOS/Linux setup script
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== VowCut Setup ==="

# 1. Check ffmpeg
if ! command -v ffmpeg &>/dev/null; then
  echo "ERROR: ffmpeg not found. Install via:"
  echo "  macOS:  brew install ffmpeg"
  echo "  Ubuntu: sudo apt install ffmpeg"
  exit 1
fi
echo "✓ ffmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"

# 2. Python venv
cd "$ROOT/backend"
if [ ! -d ".venv" ]; then
  echo "Creating Python virtual environment…"
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "Installing Python dependencies…"
pip install --upgrade pip -q
pip install -r requirements-dev.txt -q
echo "✓ Python dependencies installed"

# 3. Generate test fixture
echo "Generating test clip…"
python "$ROOT/scripts/gen_test_clip.py"

# 4. Node deps for Electron
cd "$ROOT/electron"
if command -v npm &>/dev/null; then
  echo "Installing Node dependencies…"
  npm install --silent
  echo "✓ Node dependencies installed"
else
  echo "WARN: npm not found — skip Electron dependency install"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "To run backend tests:"
echo "  cd backend && source .venv/bin/activate && pytest"
echo ""
echo "To start backend dev server:"
echo "  cd backend && source .venv/bin/activate && python -m backend.app"
echo ""
echo "To check GPU:"
echo "  python scripts/check_gpu.py"
