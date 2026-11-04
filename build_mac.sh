#!/bin/bash
# Build ASCII3DShapes.app on a Mac (GitHub Actions builds it too)
# Run this on a Mac: chmod +x build_mac.sh && ./build_mac.sh

set -e

echo "=== ASCII 3D Shapes - macOS Build ==="

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found. Install Python 3.9+ first."
    exit 1
fi

# Install dependencies if missing
python3 -m pip install --quiet -r requirements.txt pyinstaller

# The spec builds the .app, including the microphone permission text
python3 -m PyInstaller --noconfirm ASCII3DShapes.spec

dist/ASCII3DShapes.app/Contents/MacOS/ASCII3DShapes --selftest

echo ""
echo "=== Build complete ==="
echo "App: dist/ASCII3DShapes.app (double-click it, or drag it to Applications)"
echo "Terminal mode: dist/ASCII3DShapes.app/Contents/MacOS/ASCII3DShapes --terminal"
