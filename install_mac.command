#!/bin/bash
# Double-click to set up ASCII 3D Shapes for the terminal (see install.py)
cd "$(dirname "$0")" || exit 1

# On a fresh Mac, python3 offers to install Apple's developer tools first
if python3 -c 'import sys' >/dev/null 2>&1; then
    python3 install.py
else
    echo "Python 3 is not installed yet. To get it:"
    echo
    echo "  1. Go to https://www.python.org/downloads/ and download the macOS installer."
    echo "  2. Open it and follow the steps."
    echo "  3. Then double-click this file again."
fi
echo
read -n 1 -s -r -p "Press any key to close this window."
echo
