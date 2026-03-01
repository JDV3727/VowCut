# VowCut Windows setup script
param()
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Write-Host "=== VowCut Setup ===" -ForegroundColor Cyan

# 1. Check ffmpeg
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: ffmpeg not found. Install via: winget install Gyan.FFmpeg" -ForegroundColor Red
    exit 1
}
$ffver = (ffmpeg -version 2>&1 | Select-Object -First 1) -replace ".*version ",""
Write-Host "OK ffmpeg $ffver" -ForegroundColor Green

# 2. Python venv
Push-Location "$Root\backend"
if (-not (Test-Path ".venv")) {
    Write-Host "Creating Python virtual environment..."
    python -m venv .venv
}
.\.venv\Scripts\Activate.ps1

Write-Host "Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements-dev.txt -q
Write-Host "OK Python dependencies" -ForegroundColor Green

# 3. Test fixture
Write-Host "Generating test clip..."
python "$Root\scripts\gen_test_clip.py"

# 4. Node
Pop-Location
Push-Location "$Root\electron"
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host "Installing Node dependencies..."
    npm install --silent
    Write-Host "OK Node dependencies" -ForegroundColor Green
} else {
    Write-Host "WARN: npm not found — skip Electron dependency install" -ForegroundColor Yellow
}
Pop-Location

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Run tests:  cd backend; .\.venv\Scripts\Activate.ps1; pytest"
Write-Host "GPU check:  python scripts\check_gpu.py"
