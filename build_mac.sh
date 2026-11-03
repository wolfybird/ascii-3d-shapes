#!/bin/bash
# Build ASCII3DShapes.app for macOS
# Run this on a Mac: chmod +x build_mac.sh && ./build_mac.sh

set -e

echo "=== ASCII 3D Shapes - macOS Build ==="

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found. Install Python 3.8+ first."
    exit 1
fi

# Install dependencies if missing
python3 -m pip install --quiet numpy sounddevice pyinstaller

# Build .app bundle
python3 -m PyInstaller \
    --onefile \
    --name "ASCII3DShapes" \
    --console \
    --clean \
    shapes_v9-3-1.py

echo ""
echo "=== Build complete ==="
echo "Executable: dist/ASCII3DShapes"
echo ""
echo "To run: ./dist/ASCII3DShapes"
echo ""
echo "To create a proper .app wrapper (optional, for double-click from Finder):"
echo "  mkdir -p 'dist/ASCII3DShapes.app/Contents/MacOS'"
echo "  cp dist/ASCII3DShapes 'dist/ASCII3DShapes.app/Contents/MacOS/'"
echo "  The .app will open Terminal and run automatically."
