# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Smart Collage Maker
Usage: pyinstaller smart_collage_maker.spec
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import os

block_cipher = None

# Collect mediapipe data files (required for face detection)
mediapipe_datas = collect_data_files('mediapipe')
print_preview_hiddenimports = collect_submodules('print_preview')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('app/i18n', 'app/i18n'),
        ('app/assets', 'app/assets'),
    ] + mediapipe_datas,
    hiddenimports=[
        'mediapipe',
        'PIL',
        'numpy',
        'PySide6',
    ] + print_preview_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SmartCollageMaker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app/assets/icon.ico' if os.path.exists('app/assets/icon.ico') else None,
)

# Release builds use one-folder packaging because it compresses better inside
# the installer and avoids creating a second debug executable by default.
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SmartCollageMaker',
)
