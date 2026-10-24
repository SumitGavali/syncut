# -*- mode: python ; coding: utf-8 -*-
import os
import sys

block_cipher = None

# Determine base project dir
base_dir = os.path.abspath(SPECPATH)

# Binaries to bundle: ffmpeg and ffprobe
binaries = []
ffmpeg_exe = os.path.join(base_dir, "ffmpeg_bin", "ffmpeg.exe")
ffprobe_exe = os.path.join(base_dir, "ffmpeg_bin", "ffprobe.exe")
if os.path.isfile(ffmpeg_exe):
    binaries.append((ffmpeg_exe, "bin"))
if os.path.isfile(ffprobe_exe):
    binaries.append((ffprobe_exe, "bin"))

# Datas to bundle: templates, static assets
datas = [
    (os.path.join(base_dir, "templates"), "templates"),
    (os.path.join(base_dir, "static"), "static"),
]

hidden_imports = [
    'flask',
    'flask_cors',
    'scipy.signal',
    'scipy.special.cython_special',
    'scipy.optimize',
    'sklearn',
    'sklearn.isotonic',
    'platformdirs',
    'opentimelineio',
    'engineio.async_drivers.threading',
]

a = Analysis(
    ['app.py'],
    pathex=[base_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib.tests'],
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
    name='SyncCut',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Set to True so editors/studios see startup port logs
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SyncCut',
)
