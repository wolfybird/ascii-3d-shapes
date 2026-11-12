#!/bin/bash
# Build ShapeRunner.app on a Mac (GitHub Actions builds it too)
# Run this on a Mac: chmod +x build_mac.sh && ./build_mac.sh

set -e

echo "=== ShapeRunner - macOS Build ==="

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found. Install Python 3.9+ first."
    exit 1
fi

# Install dependencies if missing
python3 -m pip install --quiet -r requirements.txt pyinstaller

# The spec builds the .app, including the microphone permission text
python3 -m PyInstaller --noconfirm ShapeRunner.spec

dist/ShapeRunner.app/Contents/MacOS/ShapeRunner --selftest

echo ""
echo "=== Build complete ==="
echo "App: dist/ShapeRunner.app (double-click it, or drag it to Applications)"
echo "Terminal mode: dist/ShapeRunner.app/Contents/MacOS/ShapeRunner --terminal"
