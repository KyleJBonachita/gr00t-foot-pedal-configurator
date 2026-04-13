#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build"

cd "$ROOT_DIR"

echo "[1/3] Installing build dependencies (host only)..."
python3 -m pip install --upgrade pip pyinstaller evdev

echo "[2/3] Cleaning previous build output..."
rm -rf "$BUILD_DIR" "$DIST_DIR"

echo "[3/3] Building single executable (onefile)..."
python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name footpedal-config \
  --windowed \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  --hidden-import evdev \
  --hidden-import footswitch_linux \
  --collect-submodules evdev \
  --collect-binaries evdev \
  gui.py

chmod +x "$DIST_DIR/footpedal-config"

echo "Single executable created: $DIST_DIR/footpedal-config"
echo "Copy this one file to target Ubuntu machine and double-click it."
