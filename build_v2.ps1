$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

python -m PyInstaller ".\YouTube Downloader GUI v2.spec" --distpath ".\dist" --workpath ".\build"

Write-Host "Build complete: dist\YouTube Downloader GUI v2.exe"
