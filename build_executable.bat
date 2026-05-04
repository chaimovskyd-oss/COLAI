@echo off
REM ============================================================================
REM Smart Collage Maker - Build Standalone Executable
REM ============================================================================
REM This script builds only the standalone executable (no installer)
REM The output can be shared as a single executable file
REM ============================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================================
echo Smart Collage Maker - Build Executable
echo ============================================================================
echo.

REM Check Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python not found in PATH
    echo Please install Python 3.9+ from https://www.python.org/
    pause
    exit /b 1
)
echo [OK] Python found
python --version

REM Check PyInstaller
pip show pyinstaller >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [INSTALL] PyInstaller not found, installing...
    python -m pip install pyinstaller
)
echo [OK] PyInstaller ready

echo.
echo ============================================================================
echo Step 1: Installing Python Dependencies
echo ============================================================================
python -m pip install --upgrade -q -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo [OK] Dependencies installed

echo.
echo ============================================================================
echo Step 2: Building Executable (This may take 5-10 minutes)
echo ============================================================================
echo.

if exist build\ rmdir /s /q build >nul 2>&1
if exist dist\ rmdir /s /q dist >nul 2>&1

python -m PyInstaller smart_collage_maker.spec --distpath dist --workpath build

if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Build failed
    pause
    exit /b 1
)

if not exist "dist\SmartCollageMaker.exe" (
    echo ERROR: Executable not created
    pause
    exit /b 1
)

echo.
echo ============================================================================
echo BUILD COMPLETE!
echo ============================================================================
echo.
echo Main executable:
echo   dist\SmartCollageMaker.exe
echo.
echo To run the application:
echo   1. Copy dist\SmartCollageMaker.exe to any location
echo   2. Run SmartCollageMaker.exe
echo   3. No Python installation needed!
echo.
echo To create an installer instead, run: build_installer.bat
echo.
pause
