#!/usr/bin/env bash
set -euo pipefail
# Build the ExpertAnything one-click installer (onedir).
# Prereqs:  pip install -r requirements.txt pyinstaller
python -m PyInstaller expert_anything.spec --clean --noconfirm
echo "Build complete. Runnable at: dist/ExpertAnything/ExpertAnything"
