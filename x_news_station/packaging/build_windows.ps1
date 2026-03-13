$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --windowed `
  --name x-news-station `
  --add-data "assets;assets" `
  --add-data "station_settings.example.ini;." `
  main.py
