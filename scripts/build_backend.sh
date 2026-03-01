#!/usr/bin/env bash
# build_backend.sh — Bundle python-build-standalone + dependencies + static ffmpeg
# Output layout:
#   build/python/  <- python-build-standalone with pip-installed requirements
#   build/ffmpeg/  <- static ffmpeg + ffprobe binaries
#
# Pinned versions for reproducibility; update SHA256s when bumping versions.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$ROOT_DIR/build"

# ---------------------------------------------------------------------------
# Pinned release constants
# ---------------------------------------------------------------------------

PBS_VERSION="20240415"
PBS_PYTHON_VERSION="3.12.3"

# python-build-standalone release tag and SHA256 per platform/arch
# Update these when upgrading Python
PBS_MACOS_ARM64_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PBS_PYTHON_VERSION}+${PBS_VERSION}-aarch64-apple-darwin-install_only.tar.gz"
PBS_MACOS_ARM64_SHA256="placeholder_macos_arm64_sha256"

PBS_MACOS_X86_64_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PBS_PYTHON_VERSION}+${PBS_VERSION}-x86_64-apple-darwin-install_only.tar.gz"
PBS_MACOS_X86_64_SHA256="placeholder_macos_x86_64_sha256"

PBS_LINUX_X86_64_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PBS_PYTHON_VERSION}+${PBS_VERSION}-x86_64-unknown-linux-gnu-install_only.tar.gz"
PBS_LINUX_X86_64_SHA256="placeholder_linux_x86_64_sha256"

# Static ffmpeg (macOS: evermeet.cx builds; Linux: BtbN/FFmpeg-Builds)
FFMPEG_VERSION="7.0"

FFMPEG_MACOS_URL="https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip"
FFPROBE_MACOS_URL="https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"

FFMPEG_LINUX_URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n${FFMPEG_VERSION}-linux64-gpl.tar.xz"
FFMPEG_LINUX_SHA256="placeholder_linux_ffmpeg_sha256"

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

PLATFORM="$(uname -s)"
ARCH="$(uname -m)"

case "$PLATFORM" in
  Darwin)
    case "$ARCH" in
      arm64)
        PBS_URL="$PBS_MACOS_ARM64_URL"
        PBS_SHA256="$PBS_MACOS_ARM64_SHA256"
        ;;
      x86_64)
        PBS_URL="$PBS_MACOS_X86_64_URL"
        PBS_SHA256="$PBS_MACOS_X86_64_SHA256"
        ;;
      *)
        echo "ERROR: Unsupported macOS architecture: $ARCH" >&2
        exit 1
        ;;
    esac
    ;;
  Linux)
    if [[ "$ARCH" != "x86_64" ]]; then
      echo "ERROR: Unsupported Linux architecture: $ARCH" >&2
      exit 1
    fi
    PBS_URL="$PBS_LINUX_X86_64_URL"
    PBS_SHA256="$PBS_LINUX_X86_64_SHA256"
    ;;
  *)
    echo "ERROR: Unsupported platform: $PLATFORM" >&2
    exit 1
    ;;
esac

echo "==> Platform: $PLATFORM/$ARCH"

# ---------------------------------------------------------------------------
# Helper: verify SHA256
# ---------------------------------------------------------------------------

verify_sha256() {
  local file="$1"
  local expected="$2"

  # Skip verification for placeholder values (development mode)
  if [[ "$expected" == placeholder_* ]]; then
    echo "    [WARN] SHA256 not pinned for $file — skipping verification"
    return 0
  fi

  local actual
  if command -v sha256sum &>/dev/null; then
    actual="$(sha256sum "$file" | awk '{print $1}')"
  else
    actual="$(shasum -a 256 "$file" | awk '{print $1}')"
  fi

  if [[ "$actual" != "$expected" ]]; then
    echo "ERROR: SHA256 mismatch for $file" >&2
    echo "  expected: $expected" >&2
    echo "  actual:   $actual" >&2
    exit 1
  fi
  echo "    SHA256 OK"
}

# ---------------------------------------------------------------------------
# Step 1: Download and extract python-build-standalone
# ---------------------------------------------------------------------------

PYTHON_BUILD_DIR="$BUILD_DIR/python"

echo ""
echo "==> Step 1: python-build-standalone"

if [[ -f "$PYTHON_BUILD_DIR/bin/python3" ]] || [[ -f "$PYTHON_BUILD_DIR/python.exe" ]]; then
  echo "    Already exists — skipping download"
else
  PBS_TARBALL="$BUILD_DIR/pbs.tar.gz"
  mkdir -p "$BUILD_DIR"

  echo "    Downloading $PBS_URL …"
  curl -fsSL "$PBS_URL" -o "$PBS_TARBALL"
  verify_sha256 "$PBS_TARBALL" "$PBS_SHA256"

  echo "    Extracting …"
  mkdir -p "$PYTHON_BUILD_DIR"
  tar -xzf "$PBS_TARBALL" -C "$PYTHON_BUILD_DIR" --strip-components=1
  rm "$PBS_TARBALL"
fi

PYTHON_BIN="$PYTHON_BUILD_DIR/bin/python3"
PIP_BIN="$PYTHON_BUILD_DIR/bin/pip3"

if [[ ! -f "$PYTHON_BIN" ]]; then
  echo "ERROR: $PYTHON_BIN not found after extraction" >&2
  exit 1
fi
echo "    Python: $("$PYTHON_BIN" --version)"

# ---------------------------------------------------------------------------
# Step 2: pip install requirements
# ---------------------------------------------------------------------------

echo ""
echo "==> Step 2: pip install requirements"

REQUIREMENTS="$ROOT_DIR/backend/requirements.txt"
if [[ ! -f "$REQUIREMENTS" ]]; then
  echo "ERROR: $REQUIREMENTS not found" >&2
  exit 1
fi

"$PIP_BIN" install --quiet -r "$REQUIREMENTS"
echo "    Done"

# ---------------------------------------------------------------------------
# Step 3: Download static ffmpeg
# ---------------------------------------------------------------------------

FFMPEG_BUILD_DIR="$BUILD_DIR/ffmpeg"

echo ""
echo "==> Step 3: Static ffmpeg"

if [[ -f "$FFMPEG_BUILD_DIR/ffmpeg" ]] && [[ -f "$FFMPEG_BUILD_DIR/ffprobe" ]]; then
  echo "    Already exists — skipping download"
else
  mkdir -p "$FFMPEG_BUILD_DIR"

  if [[ "$PLATFORM" == "Darwin" ]]; then
    echo "    Downloading ffmpeg (macOS) from evermeet.cx …"
    curl -fsSL "$FFMPEG_MACOS_URL" -o "$BUILD_DIR/ffmpeg.zip"
    unzip -q "$BUILD_DIR/ffmpeg.zip" -d "$FFMPEG_BUILD_DIR"
    rm "$BUILD_DIR/ffmpeg.zip"

    echo "    Downloading ffprobe (macOS) from evermeet.cx …"
    curl -fsSL "$FFPROBE_MACOS_URL" -o "$BUILD_DIR/ffprobe.zip"
    unzip -q "$BUILD_DIR/ffprobe.zip" -d "$FFMPEG_BUILD_DIR"
    rm "$BUILD_DIR/ffprobe.zip"
  else
    # Linux
    echo "    Downloading ffmpeg (Linux) …"
    FFMPEG_TARBALL="$BUILD_DIR/ffmpeg.tar.xz"
    curl -fsSL "$FFMPEG_LINUX_URL" -o "$FFMPEG_TARBALL"
    verify_sha256 "$FFMPEG_TARBALL" "$FFMPEG_LINUX_SHA256"

    tar -xJf "$FFMPEG_TARBALL" -C "$BUILD_DIR"
    # BtbN builds extract to a versioned dir; find and copy binaries
    FFMPEG_EXTRACTED=$(find "$BUILD_DIR" -maxdepth 2 -name "ffmpeg" -not -path "$FFMPEG_BUILD_DIR/*" | head -1)
    if [[ -z "$FFMPEG_EXTRACTED" ]]; then
      echo "ERROR: ffmpeg binary not found in extracted tarball" >&2
      exit 1
    fi
    EXTRACTED_DIR="$(dirname "$FFMPEG_EXTRACTED")"
    cp "$EXTRACTED_DIR/ffmpeg" "$FFMPEG_BUILD_DIR/ffmpeg"
    cp "$EXTRACTED_DIR/ffprobe" "$FFMPEG_BUILD_DIR/ffprobe"
    rm "$FFMPEG_TARBALL"
    rm -rf "$EXTRACTED_DIR"
  fi

  chmod +x "$FFMPEG_BUILD_DIR/ffmpeg" "$FFMPEG_BUILD_DIR/ffprobe"
fi

echo "    ffmpeg: $("$FFMPEG_BUILD_DIR/ffmpeg" -version 2>&1 | head -1)"
echo "    ffprobe: $("$FFMPEG_BUILD_DIR/ffprobe" -version 2>&1 | head -1)"

# ---------------------------------------------------------------------------
# Step 4: Smoke test
# ---------------------------------------------------------------------------

echo ""
echo "==> Step 4: Smoke test"

"$PYTHON_BIN" -c "
import importlib, sys
failures = []
for mod in ['duckdb', 'librosa', 'numpy', 'fastapi']:
    try:
        importlib.import_module(mod)
    except ImportError as e:
        failures.append(f'{mod}: {e}')
if failures:
    for f in failures:
        print(f'FAIL: {f}', file=sys.stderr)
    sys.exit(1)
print('All imports OK')
"

# ---------------------------------------------------------------------------
# Step 5: Size summary
# ---------------------------------------------------------------------------

echo ""
echo "==> Build complete"
du -sh "$PYTHON_BUILD_DIR" "$FFMPEG_BUILD_DIR" 2>/dev/null || true
