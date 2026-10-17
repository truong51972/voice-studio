@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo [ERROR] uv is not installed. Install from https://docs.astral.sh/uv/ and retry.
  exit /b 1
)
echo [1/4] Setting up Python and all production runtimes...
uv sync --locked
if errorlevel 1 exit /b 1
echo [2/4] Downloading/verifying original Locator speaker models...
uv run poe models
if errorlevel 1 exit /b 1
echo [3/4] Building Windows onedir distribution...
uv run python scripts/build.py
if errorlevel 1 exit /b 1
echo [4/4] Archiving checked executable...
uv run python scripts/release_zip.py --platform windows
if errorlevel 1 exit /b 1
echo [OK] See dist\VoiceStudio-*-windows-x64.zip
endlocal
