@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo [ERROR] uv is not installed. Install from https://docs.astral.sh/uv/ and retry.
  exit /b 1
)
echo [1/3] Setting up Python and all production runtimes...
uv python install 3.12
if errorlevel 1 exit /b 1
uv sync --locked --python 3.12
if errorlevel 1 exit /b 1
echo [2/3] Building Windows onedir distribution...
uv run python scripts/build.py
if errorlevel 1 exit /b 1
echo [3/3] Archiving checked executable...
uv run python scripts/release_zip.py --platform windows
if errorlevel 1 exit /b 1
echo [OK] See dist\VoiceStudio-*-windows-x64.zip
endlocal
