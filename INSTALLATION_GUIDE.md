# Smart Collage Maker - Installation Guide

This guide explains how to build and create a standalone installer for Smart Collage Maker using PyInstaller and Inno Setup.

## Prerequisites

You need to have the following installed on your development machine:

### 1. Python 3.9+
Download from https://www.python.org/

### 2. PyInstaller
Install PyInstaller to create the standalone executable:
```bash
pip install pyinstaller
```

### 3. Inno Setup Compiler
Download and install from https://jrsoftware.org/isinfo.php

## Build Instructions

### Step 1: Install Dependencies

Navigate to the project folder and install all required Python packages:

```bash
cd C:\Users\chaim\Downloads\COLAI\collage_mvp
pip install -r requirements.txt
```

This installs:
- **PySide6** (≥6.6) - Qt GUI framework
- **Pillow** (≥10.0) - Image processing
- **mediapipe** (≥0.10) - Face detection
- **numpy** (≥1.24) - Numerical computing

### Step 2: Build the Executable with PyInstaller

Run PyInstaller using the provided spec file:

```bash
pyinstaller smart_collage_maker.spec
```

This will:
- Compile all Python code into a standalone executable
- Bundle all dependencies (PySide6, Pillow, numpy, mediapipe)
- Include all data files (translations, assets)
- Create the output in `dist\SmartCollageMaker\` folder

**Note:** This process may take 5-10 minutes due to the size of the dependencies, especially mediapipe.

After completion, you should see:
```
dist/
  SmartCollageMaker/
    SmartCollageMaker.exe       (Main executable)
    SmartCollageMaker_console.exe (Debug version)
    (many DLL files and data folders)
```

### Step 3: Test the Executable (Optional)

Before creating the installer, test that the standalone executable works:

```bash
dist\SmartCollageMaker\SmartCollageMaker.exe
```

The application should launch without requiring any Python installation.

### Step 4: Create the Installer with Inno Setup

Open **Inno Setup Compiler** and:

1. **File** → **Open** 
2. Navigate to: `SmartCollageMaker.iss`
3. **Build** → **Compile**

Alternatively, from command line:
```bash
"C:\Program Files (x86)\Inno Setup 6\iscc.exe" SmartCollageMaker.iss
```

The installer will be created as:
```
dist/SmartCollageMaker_Setup.exe
```

## Installation on Target Machine

The installer file `SmartCollageMaker_Setup.exe` can be distributed to any Windows PC (64-bit, Windows 7 or later).

### User Installation Steps

1. Run `SmartCollageMaker_Setup.exe`
2. Choose installation folder (default: `C:\Program Files\Smart Collage Maker`)
3. Choose whether to create desktop/Start Menu shortcuts
4. Click "Install"
5. The application launches automatically when done

**No additional software is required** - the installer includes:
- Python runtime (bundled with PyInstaller)
- All Python dependencies
- All application data and translations
- Localization support (English and Hebrew)

## File Structure

After installation on target machine:

```
C:\Program Files\Smart Collage Maker\
  SmartCollageMaker.exe              (Main application)
  SmartCollageMaker_console.exe      (Debug console version)
  [PySide6 DLLs and data files]      (Qt framework)
  [numpy DLLs]                       (Numerical computing)
  [Pillow libraries]                 (Image processing)
  [mediapipe models]                 (Face detection AI models)
  app/
    i18n/                            (Translations: English, Hebrew)
    assets/                          (Icons, resources)
    [all Python modules]
```

## Troubleshooting

### Issue: PyInstaller build fails

**Solution:** Ensure all dependencies are installed:
```bash
pip install --upgrade -r requirements.txt
```

### Issue: "Windows protected your PC" warning on installer

**Solution:** This is normal for unsigned installers. Click "More info" → "Run anyway"

### Issue: Application crashes on startup

**Possible causes:**
- Invalid system PATH or environment
- Corrupted installation - reinstall
- Missing Visual C++ Redistributable (though PyInstaller usually bundles this)

If needed, install Visual C++ Redistributable:
https://support.microsoft.com/en-us/help/2977003/

### Issue: Face detection not working

**Solution:** Ensure mediapipe data is properly included. Verify the installation contains:
```
[Installation Folder]\app_internal\mediapipe\*
```

If missing, rebuild with:
```bash
pyinstaller smart_collage_maker.spec --clean
```

## Distribution

You can now distribute `dist/SmartCollageMaker_Setup.exe` to users. The installer is:

✅ **Self-contained** - No Python installation required
✅ **Single file** - Easy to download and share
✅ **Multilingual** - English and Hebrew UI support
✅ **Standard installer** - Familiar Windows installation wizard
✅ **Uninstallable** - Full uninstall support from Control Panel

## For Developers

### Modifying the Spec File

Edit `smart_collage_maker.spec` to:
- Change icon: Update `icon='app/assets/icon.ico'`
- Add hidden imports: Add to `hiddenimports=[...]`
- Include additional data files: Add to `datas=[...]`
- Change executable name: Modify `name='SmartCollageMaker'`

### Modifying the Installer

Edit `SmartCollageMaker.iss` to:
- Change version: Update `AppVersion=1.0.0`
- Customize shortcuts: Modify `[Icons]` section
- Change installation path: Modify `DefaultDirName`
- Add license screen: Set valid `LicenseFile=LICENSE.txt`

## Build Automation (Optional)

Create `build.bat` for one-click building:

```batch
@echo off
echo Building Smart Collage Maker...
echo.
echo Step 1: Creating executable with PyInstaller...
pyinstaller smart_collage_maker.spec
if %ERRORLEVEL% NEQ 0 (
    echo PyInstaller failed!
    exit /b 1
)
echo.
echo Step 2: Creating installer with Inno Setup...
"C:\Program Files (x86)\Inno Setup 6\iscc.exe" SmartCollageMaker.iss
if %ERRORLEVEL% NEQ 0 (
    echo Inno Setup failed!
    exit /b 1
)
echo.
echo Build complete! Installer is at: dist\SmartCollageMaker_Setup.exe
pause
```

Run: `build.bat`

## Version Control

Recommended `.gitignore` additions:

```
# Build artifacts
build/
dist/
*.spec.bak
__pycache__/

# Inno Setup output
*.exe

# IDE
.vscode/
.idea/
*.pyc
```

## Support

For issues with:
- **PyInstaller**: https://github.com/pyinstaller/pyinstaller
- **Inno Setup**: https://jrsoftware.org/
- **Smart Collage Maker**: Check README.md or project documentation

---

**Last updated:** 2026-04-19
**Version:** 1.0
