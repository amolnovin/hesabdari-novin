@echo off
REM ===================================================================
REM  Build Hesabdar.exe for Windows
REM  This file is intentionally ASCII-only and CRLF-terminated:
REM  cmd.exe mangles UTF-8 Persian text and LF-only line endings.
REM  All real work is delegated to build_exe.py (Python).
REM ===================================================================
setlocal
cd /d "%~dp0"

echo ===================================================================
echo   Building Hesabdar.exe
echo   Folder: %CD%
echo ===================================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found in PATH.
  echo         Install Python from https://www.python.org
  echo         and tick "Add Python to PATH" during setup.
  echo         Then run this file again.
  pause
  exit /b 1
)

echo [1/3] Installing requirements (PySide6)...
python -m pip install --user -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Could not install requirements.
  echo         Check your internet connection / proxy settings.
  pause
  exit /b 1
)

echo [2/3] Installing PyInstaller...
python -m pip install --user pyinstaller
if errorlevel 1 (
  echo [ERROR] Could not install PyInstaller.
  pause
  exit /b 1
)

echo [3/3] Building the executable (this may take a few minutes)...
python build_exe.py
if errorlevel 1 (
  echo [ERROR] Build failed - see the messages above.
  pause
  exit /b 1
)

echo.
echo ===================================================================
echo   Done. Output: dist\Hesabdar\Hesabdar.exe
echo ===================================================================
pause
