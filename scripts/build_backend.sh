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

# python-build-standalone — SHA256s from the official SHA256SUMS file at:
# https://github.com/astral-sh/python-build-standalone/releases/download/20240415/SHA256SUMS
PBS_MACOS_ARM64_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PBS_PYTHON_VERSION}+${PBS_VERSION}-aarch64-apple-darwin-install_only.tar.gz"
PBS_MACOS_ARM64_SHA256="ccc40e5af329ef2af81350db2a88bbd6c17b56676e82d62048c15d548401519e"

PBS_MACOS_X86_64_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PBS_PYTHON_VERSION}+${PBS_VERSION}-x86_64-apple-darwin-install_only.tar.gz"
PBS_MACOS_X86_64_SHA256="c37a22fca8f57d4471e3708de6d13097668c5f160067f264bb2b18f524c890c8"

PBS_LINUX_X86_64_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PBS_PYTHON_VERSION}+${PBS_VERSION}-x86_64-unknown-linux-gnu-install_only.tar.gz"
PBS_LINUX_X86_64_SHA256="a73ba777b5d55ca89edef709e6b8521e3f3d4289581f174c8699adfb608d09d6"

# Static ffmpeg
# macOS: evermeet.cx versioned builds (8.0.1)
FFMPEG_MACOS_VERSION="8.0.1"
FFMPEG_MACOS_URL="https://evermeet.cx/ffmpeg/ffmpeg-${FFMPEG_MACOS_VERSION}.zip"
FFMPEG_MACOS_SHA256="470e482f6e290eac92984ac12b2d67bad425b1e5269fd75fb6a3536c16e824e4"
FFPROBE_MACOS_URL="https://evermeet.cx/ffmpeg/ffprobe-${FFMPEG_MACOS_VERSION}.zip"
FFPROBE_MACOS_SHA256="219a3fcb26b6650b63989b0f151b47a13417c58b5b03924ef684416797b2ed7d"

# Linux: BtbN pinned autobuild (7.1.3 GPL static) — SHA256 from official checksums.sha256:
# https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2025-11-30-12-53/checksums.sha256
FFMPEG_LINUX_RELEASE="autobuild-2025-11-30-12-53"
FFMPEG_LINUX_URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/${FFMPEG_LINUX_RELEASE}/ffmpeg-n7.1.3-7-gf65fc0b137-linux64-gpl-7.1.tar.xz"
FFMPEG_LINUX_SHA256="8d6bd76844206590809af4c5307968d39f9f8ab488d7aaf523e61b7fae2d41c8"

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
    echo "    Downloading ffmpeg ${FFMPEG_MACOS_VERSION} (macOS) from evermeet.cx …"
    curl -fsSL "$FFMPEG_MACOS_URL" -o "$BUILD_DIR/ffmpeg.zip"
    verify_sha256 "$BUILD_DIR/ffmpeg.zip" "$FFMPEG_MACOS_SHA256"
    unzip -q "$BUILD_DIR/ffmpeg.zip" -d "$FFMPEG_BUILD_DIR"
    rm "$BUILD_DIR/ffmpeg.zip"

    echo "    Downloading ffprobe ${FFMPEG_MACOS_VERSION} (macOS) from evermeet.cx …"
    curl -fsSL "$FFPROBE_MACOS_URL" -o "$BUILD_DIR/ffprobe.zip"
    verify_sha256 "$BUILD_DIR/ffprobe.zip" "$FFPROBE_MACOS_SHA256"
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
