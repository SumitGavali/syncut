# -*- mode: python ; coding: utf-8 -*-
"""
SyncCut Studio — Bulletproof PyInstaller Spec (One-Dir, MSIX & Store Ready).

Build Command:
  pyinstaller --noconfirm --clean build.spec

Output:
  dist/SyncCutStudio/  (Pack this directory into the MSIX container)
"""
from __future__ import annotations
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve()

# ---------------------------------------------------------------------------
# Input Verification
# ---------------------------------------------------------------------------
dist_ui = ROOT / "synccut-studio" / "dist"
if not (dist_ui / "index.html").is_file():
    raise FileNotFoundError(f"React build missing at {dist_ui}. Run 'npm run build' in synccut-studio first.")

ffmpeg_exe = ROOT / "ffmpeg_bin" / "ffmpeg.exe"
if not ffmpeg_exe.is_file():
    raise FileNotFoundError(f"FFmpeg binary missing at {ffmpeg_exe}.")

# ---------------------------------------------------------------------------
# Data Assets
# ---------------------------------------------------------------------------
datas = [
    (str(ROOT / "synccut-studio" / "dist"), "synccut-studio/dist"),
    (str(ROOT / "synccut" / "ai" / "models"), "synccut/ai/models"),
    (str(ROOT / "synccut" / "api" / "templates"), "synccut/api/templates"),
    (str(ROOT / ".env"), "."),
    (str(ROOT / "synccut_icon.ico"), "."),
]

# ---------------------------------------------------------------------------
# Binaries (FFmpeg + FFprobe)
# ---------------------------------------------------------------------------
binaries = [
    (str(ROOT / "ffmpeg_bin" / "ffmpeg.exe"), "ffmpeg_bin"),
    (str(ROOT / "ffmpeg_bin" / "ffprobe.exe"), "ffmpeg_bin"),
]

# ---------------------------------------------------------------------------
# Collect dynamic packages (SoundFile, Librosa, OpenCV, PyWebView, Matplotlib, ReportLab)
# ---------------------------------------------------------------------------
for pkg in ["soundfile", "librosa", "cv2", "webview", "clr_loader", "matplotlib", "reportlab", "scipy", "numpy"]:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas.extend(pkg_datas)
        binaries.extend(pkg_binaries)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Hidden Imports
# ---------------------------------------------------------------------------
hiddenimports = [
    # Desktop UI
    "webview",
    "clr",
    "pythonnet",
    "clr_loader",
    # Flask & Web
    "flask",
    "flask_cors",
    "jinja2",
    "werkzeug",
    "werkzeug.security",
    "werkzeug.serving",
    "werkzeug.routing",
    # Database
    "sqlalchemy",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.pool",
    # AI, Audio & Math
    "cv2",
    "onnxruntime",
    "librosa",
    "soundfile",
    "scipy",
    "scipy.io.wavfile",
    "scipy.optimize",
    "scipy.signal",
    "scipy.fft",
    "numpy",
    "matplotlib",
    "matplotlib.pyplot",
    "reportlab",
    # Auth & System
    "google.auth",
    "google.oauth2.id_token",
    "dotenv",
    "platformdirs",
    # Celery fallback compat
    "celery",
    "celery.fixups",
    "celery.fixups.django",
    "celery.fixups.user_settings",
]

# Add all internal synccut submodules automatically
hiddenimports.extend(collect_submodules("synccut"))

# ---------------------------------------------------------------------------
# Safe Excludes (Only libraries definitely not used anywhere in the codebase)
# ---------------------------------------------------------------------------
excludes = [
    "torch",
    "torchvision",
    "torchaudio",
    "tensorflow",
    "tensorboard",
    "paddle",
    "gradio",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "tkinter",
]

# ---------------------------------------------------------------------------
# Analysis & Build
# ---------------------------------------------------------------------------
a = Analysis(
    ["desktop_launcher.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SyncCutStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "synccut_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SyncCutStudio",
)
