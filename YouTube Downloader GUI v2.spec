# -*- mode: python ; coding: utf-8 -*-

import glob
import os
import shutil


def ffmpeg_binaries():
    binaries = []
    # 1. Local project folder
    local_ffmpeg = os.path.join(os.getcwd(), "ffmpeg.exe")
    local_ffprobe = os.path.join(os.getcwd(), "ffprobe.exe")
    if os.path.isfile(local_ffmpeg) and os.path.isfile(local_ffprobe):
        return [(local_ffmpeg, "."), (local_ffprobe, ".")]

    # 2. System PATH ffmpeg + companion ffprobe
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        ffprobe_path = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe.exe")
        if os.path.isfile(ffprobe_path):
            return [(ffmpeg_path, "."), (ffprobe_path, ".")]
        return [(ffmpeg_path, ".")]

    # 3. WinGet fallback
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        winget_ffmpegs = glob.glob(os.path.join(
            local_appdata, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg_*", "ffmpeg-*", "bin", "ffmpeg.exe"
        ))
        if winget_ffmpegs:
            f_path = winget_ffmpegs[0]
            p_path = os.path.join(os.path.dirname(f_path), "ffprobe.exe")
            binaries.append((f_path, "."))
            if os.path.isfile(p_path):
                binaries.append((p_path, "."))
            return binaries

    return binaries


excluded_modules = [
    "PySide6.QtQuick",
    "PySide6.QtQml",
    "PySide6.QtQmlModels",
    "PySide6.QtPdf",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtTest",
    "PySide6.QtUiTools",
    "PySide6.QtXml",
    "PySide6.QtSql",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtMultimedia",
    "PySide6.QtPrintSupport",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=ffmpeg_binaries(),
    datas=[("assets/tarikyt_icon.png", "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=1,
)

# Filter binaries: Remove duplicate XAMPP OpenSSL & unused software opengl if present
filtered_binaries = []
for name, path, typecode in a.binaries:
    p_lower = path.lower()
    if "libcrypto-3-x64.dll" in p_lower:
        continue
    if "opengl32sw.dll" in p_lower:
        continue
    filtered_binaries.append((name, path, typecode))

a.binaries = filtered_binaries

# Filter datas: Remove unused foreign language Qt translations (.qm files)
filtered_datas = []
for name, path, typecode in a.datas:
    p_lower = path.lower()
    if p_lower.endswith(".qm") and "pyside6" in p_lower:
        continue
    filtered_datas.append((name, path, typecode))

a.datas = filtered_datas

pyz = PYZ(a.pure, optimize=1)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TarikYT",
    icon="assets/tarikyt_icon.png",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
