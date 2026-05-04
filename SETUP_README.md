# Smart Collage Maker - Setup & Distribution Guide

This folder contains everything needed to build and distribute Smart Collage Maker as a standalone application.

## 📁 Setup Files

### Core Setup Files

| File | Purpose |
|------|---------|
| `smart_collage_maker.spec` | PyInstaller configuration - defines how to build the standalone executable |
| `SmartCollageMaker.iss` | Inno Setup configuration - defines how to create the installer |
| `build_installer.bat` | **[RECOMMENDED]** One-click build script - builds both executable and installer |
| `build_executable.bat` | Quick build script - builds only the standalone executable |
| `INSTALLATION_GUIDE.md` | Detailed step-by-step installation instructions |

### What to Do

#### For Most Users: One-Click Build

1. **Install prerequisites** (one time):
   ```bash
   pip install pyinstaller
   ```
   
   Download Inno Setup from: https://jrsoftware.org/isinfo.php

2. **Run the build script**:
   ```batch
   build_installer.bat
   ```

3. **Done!** Your installer will be at: `dist\SmartCollageMaker_Setup.exe`

#### For Quick Executable Only (No Installer)

If you just want the standalone executable folder without an installer:

```batch
build_executable.bat
```

Output: `dist\SmartCollageMaker\` folder

---

## 🔧 What Gets Built

### Option 1: Full Installer (`build_installer.bat`)

**Output:** `dist\SmartCollageMaker_Setup.exe` (~200-300 MB)

This creates a professional Windows installer that:
- ✅ Single executable file
- ✅ Familiar Windows installation wizard
- ✅ Creates Start Menu shortcuts
- ✅ Creates Desktop shortcut (optional)
- ✅ Full uninstall support
- ✅ Multilingual (English & Hebrew)
- ✅ Nothing else needed - no Python, no dependencies

**Best for:** Distribution to end users

### Option 2: Standalone Executable (`build_executable.bat`)

**Output:** `dist\SmartCollageMaker\` folder (~200-300 MB)

This creates a folder containing:
- ✅ Standalone executable
- ✅ All dependencies bundled
- ✅ All data files and translations included
- ✅ No Python installation required
- ✅ Can be zipped and shared

**Best for:** Development, testing, or direct folder distribution

---

## 📋 Requirements Before Building

### Step 1: Install Python (if not already installed)

Download from: https://www.python.org/downloads/

Verify installation:
```bash
python --version
```

Should show Python 3.9 or higher.

### Step 2: Install PyInstaller

```bash
pip install pyinstaller
```

### Step 3: Install Inno Setup (for installer only)

Download from: https://jrsoftware.org/isinfo.php

Install with default settings. The build scripts will find it automatically.

---

## 🚀 Build Process Explained

### What Happens When You Run `build_installer.bat`

```
1. [Check Dependencies]
   - Verify Python is installed
   - Verify PyInstaller is installed
   - Verify Inno Setup is installed
   
2. [Install Python Packages]
   - pip install -r requirements.txt
   - Installs: PySide6, Pillow, mediapipe, numpy
   
3. [Build Executable]
   - pyinstaller smart_collage_maker.spec
   - Compiles Python code into standalone .exe
   - Bundles all libraries and data files
   - Creates: dist/SmartCollageMaker/
   - Duration: 5-10 minutes (mediapipe is large)
   
4. [Test Executable]
   - Launches the app for 5 seconds
   - Verifies the build worked
   
5. [Create Installer]
   - Inno Setup compiles SmartCollageMaker.iss
   - Packages everything into: SmartCollageMaker_Setup.exe
   - Size: ~200-300 MB
```

---

## 📦 Distribution

Once you have `SmartCollageMaker_Setup.exe`:

### Distribute to Users

1. Upload to your website or file hosting
2. Users download `SmartCollageMaker_Setup.exe`
3. Users run the installer
4. Application is installed and ready to use
5. **No Python, no pip, no dependencies needed!**

### User Installation Experience

```
User receives: SmartCollageMaker_Setup.exe

User runs installer:
  - Clicks through setup wizard
  - Chooses install location (default: C:\Program Files\Smart Collage Maker)
  - Chooses shortcuts (Desktop, Start Menu)
  - Clicks "Install"
  - Application launches automatically

Application is ready:
  - All dependencies are included
  - Multi-language support (English/Hebrew)
  - Can create projects, import images, export collages
  - Full functionality available
```

---

## 🔍 Troubleshooting

### Build Fails: "PyInstaller not found"

```bash
pip install pyinstaller
build_installer.bat
```

### Build Fails: "Python not found"

Make sure Python is installed and in your PATH:
```bash
python --version
```

If not in PATH, reinstall Python and check "Add Python to PATH" during installation.

### Build Takes Very Long

This is normal - mediapipe models are large. The build may take 10-15 minutes. Be patient.

### Installer Shows Security Warning

This is normal for unsigned executables. Users can click "More info" → "Run anyway"

To remove the warning, you would need to digitally sign the executable (requires a code signing certificate).

### Application Crashes After Installation

1. Try uninstalling and reinstalling
2. Ensure Windows 7 or newer
3. Verify user has disk space available
4. Check if Windows Defender is blocking it (add to whitelist)

---

## 📝 Customization

### Change Application Icon

1. Replace or create `app/assets/icon.ico` (256×256 PNG converted to ICO)
2. Both spec file and Inno Setup script reference this file
3. Rebuild with the script

### Change Installer Appearance

Edit `SmartCollageMaker.iss`:
- App name: `AppName=Smart Collage Maker`
- Version: `AppVersion=1.0.0`
- Publisher: `AppPublisher=Smart Collage Team`
- Installation folder: `DefaultDirName={autopf}\Smart Collage Maker`

### Change Executable Name

Edit `smart_collage_maker.spec`:
- Change: `name='SmartCollageMaker'` to `name='YourAppName'`
- Update `.iss` file accordingly

---

## 🏗️ Build Automation (Optional)

### GitHub Actions (CI/CD)

To automatically build on every commit, create `.github/workflows/build.yml`:

```yaml
name: Build Installer

on: [push, pull_request]

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: pip install -r requirements.txt pyinstaller
      - name: Build with PyInstaller
        run: pyinstaller smart_collage_maker.spec
      - name: Install Inno Setup
        run: choco install innosetup -y
      - name: Create installer
        run: iscc.exe SmartCollageMaker.iss
      - name: Upload artifact
        uses: actions/upload-artifact@v2
        with:
          name: SmartCollageMaker_Setup
          path: dist/SmartCollageMaker_Setup.exe
```

---

## ✅ Verification Checklist

Before distributing, verify:

- [ ] Executable launches without errors
- [ ] All UI text is correct (English & Hebrew)
- [ ] Image import works
- [ ] Layout generation works
- [ ] Face detection works (if MediaPipe installed)
- [ ] Export works (PNG, PDF)
- [ ] Settings persist across restarts
- [ ] Undo/Redo work correctly
- [ ] All menu items are functional

---

## 📊 File Sizes (Approximate)

| File | Size | Notes |
|------|------|-------|
| `dist/SmartCollageMaker/` | 200-300 MB | Includes all dependencies |
| `SmartCollageMaker_Setup.exe` | 200-300 MB | Compressed installer |
| Installed on disk | 400-500 MB | After extraction and installation |

---

## 🔗 Resources

- **PyInstaller Documentation**: https://pyinstaller.readthedocs.io/
- **Inno Setup Documentation**: https://jrsoftware.org/ishelp/
- **Python**: https://www.python.org/
- **PySide6**: https://www.qt.io/qt-for-python
- **Pillow**: https://pillow.readthedocs.io/
- **MediaPipe**: https://google.github.io/mediapipe/

---

## 📄 License

Smart Collage Maker is distributed under its original license. See LICENSE.txt for details.

---

## 🤝 Support

For issues with:
- **Building**: Check INSTALLATION_GUIDE.md
- **PyInstaller**: https://github.com/pyinstaller/pyinstaller
- **Inno Setup**: https://jrsoftware.org/
- **Application**: Check main README.md

---

**Last Updated:** April 19, 2026
**Setup Version:** 1.0
