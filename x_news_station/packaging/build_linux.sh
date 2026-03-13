#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

python -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --windowed \
  --name x-news-station \
  --add-data "assets:assets" \
  --add-data "station_settings.example.ini:." \
  main.py
