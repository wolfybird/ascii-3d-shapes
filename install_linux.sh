#!/bin/bash
# Set up ShapeRunner for the terminal (see install.py):  ./install_linux.sh
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is not installed yet. Install it with your package manager:"
    echo
    echo "  sudo apt install python3 python3-venv    (Ubuntu, Debian, Mint)"
    echo "  sudo dnf install python3                 (Fedora)"
    echo "  sudo pacman -S python                    (Arch)"
    echo
    echo "Then run this again."
    exit 1
fi

python3 install.py
