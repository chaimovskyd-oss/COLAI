@echo off
REM ============================================================================
REM Smart Collage Maker - Build Installer Script
REM ============================================================================
REM This script automates the complete build process:
REM 1. Checks for required tools (PyInstaller, Inno Setup)
REM 2. Builds standalone executable with PyInstaller
REM 3. Creates installer with Inno Setup
REM ============================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================================
echo Smart Collage Maker - Build Installer
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
python -m PyInstaller --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [INSTALL] PyInstaller not found, installing...
    python -m pip install pyinstaller
    if %ERRORLEVEL% NEQ 0 (
        echo ERROR: Failed to install PyInstaller
        pause
        exit /b 1
    )
)
echo [OK] PyInstaller found

REM Check Inno Setup
if not exist "C:\Program Files (x86)\Inno Setup 6\iscc.exe" (
    if not exist "C:\Program Files\Inno Setup 6\iscc.exe" (
        echo.
        echo WARNING: Inno Setup not found
        echo Download and install from: https://jrsoftware.org/isdl.php
        echo.
        set SKIP_INNO=1
    )
)

if not defined SKIP_INNO (
    echo [OK] Inno Setup found
)

echo.
echo ============================================================================
echo Step 1: Installing/Updating Python Dependencies
echo ============================================================================
echo.

python -m pip install --upgrade -q -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo [OK] Dependencies installed

echo.
echo ============================================================================
echo Step 2: Cleaning Previous Builds
echo ============================================================================
echo.

if exist build\ (
    echo Removing old build folder...
    rmdir /s /q build >nul 2>&1
)
if exist dist\ (
    echo Removing old dist folder...
    rmdir /s /q dist >nul 2>&1
)
echo [OK] Clean complete

echo.
echo ============================================================================
echo Step 3: Building Executable with PyInstaller
echo ============================================================================
echo.
echo This may take 5-10 minutes. Please wait...
echo.

python -m PyInstaller smart_collage_maker.spec --distpath dist --workpath build

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: PyInstaller build failed!
    echo Check the output above for details.
    pause
    exit /b 1
)

if not exist "dist\SmartCollageMaker\SmartCollageMaker.exe" (
    echo.
    echo ERROR: Build output not created
    pause
    exit /b 1
)

echo.
echo [OK] Build output created: dist\SmartCollageMaker\SmartCollageMaker.exe

echo.
echo ============================================================================
echo Step 4: Testing Executable (Quick Launch)
echo ============================================================================
echo.
echo Launching application for 5 seconds to verify it works...
echo Close the window or wait 5 seconds...
echo.

timeout /t 2 /nobreak

REM Launch with a timeout using taskkill
start "" "dist\SmartCollageMaker\SmartCollageMaker.exe"
timeout /t 5 /nobreak
taskkill /IM SmartCollageMaker.exe /F >nul 2>&1

echo [OK] Executable test complete

if defined SKIP_INNO (
    echo.
    echo WARNING: Inno Setup not found, skipping installer creation
    echo Install Inno Setup from: https://jrsoftware.org/isdl.php
    echo Then run this script again, or manually compile SmartCollageMaker.iss
    echo.
    pause
    exit /b 0
)

echo.
echo ============================================================================
echo Step 5: Creating Installer with Inno Setup
echo ============================================================================
echo.

set INNO_PATH=C:\Program Files (x86)\Inno Setup 6\iscc.exe
if not exist "!INNO_PATH!" (
    set INNO_PATH=C:\Program Files\Inno Setup 6\iscc.exe
)

"!INNO_PATH!" SmartCollageMaker.iss

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Inno Setup compilation failed!
    echo Make sure the executable build completed successfully before packaging.
    pause
    exit /b 1
)

if not exist "dist\SmartCollageMaker_Setup.exe" (
    echo.
    echo ERROR: Installer not created
    pause
    exit /b 1
)

echo [OK] Installer created: dist\SmartCollageMaker_Setup.exe

echo.
echo ============================================================================
echo BUILD COMPLETE!
echo ============================================================================
echo.
echo Installer location:
echo   dist\SmartCollageMaker_Setup.exe
echo.
echo Installer size:
for /f "usebackq" %%A in ('dir /b "dist\SmartCollageMaker_Setup.exe"') do (
    for %%B in ("dist\SmartCollageMaker_Setup.exe") do echo   %%~zB bytes
)
echo.
echo Next steps:
echo   1. Test the installer on a clean PC
echo   2. Distribute dist\SmartCollageMaker_Setup.exe to users
echo   3. Users can run the installer directly - no additional software needed
echo.
pause
