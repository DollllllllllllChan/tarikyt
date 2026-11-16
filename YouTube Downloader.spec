# -*- mode: python ; coding: utf-8 -*-

import glob
import os
import shutil


def ffmpeg_binaries():
    candidates = []
    local_root = os.getcwd()
    local_appdata = os.environ.get("LOCALAPPDATA", "")

    for name in ("ffmpeg.exe", "ffprobe.exe"):
        candidates.append(os.path.join(local_root, name))

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        candidates.append(ffmpeg_path)
        candidates.append(os.path.join(os.path.dirname(ffmpeg_path), "ffprobe.exe"))

    if local_appdata:
        candidates.extend(glob.glob(os.path.join(
            local_appdata,
            "Microsoft",
            "WinGet",
            "Packages",
            "Gyan.FFmpeg_*",
            "ffmpeg-*",
            "bin",
            "ffmpeg.exe",
        )))
        candidates.extend(glob.glob(os.path.join(
            local_appdata,
            "Microsoft",
            "WinGet",
            "Packages",
            "Gyan.FFmpeg_*",
            "ffmpeg-*",
            "bin",
            "ffprobe.exe",
        )))

    binaries = []
    seen = set()
    for path in candidates:
        try:
            normalized = os.path.normcase(os.path.abspath(path))
            if normalized in seen or not os.path.isfile(path):
                continue
            seen.add(normalized)
            binaries.append((path, "."))
        except OSError:
            continue

    return binaries


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=ffmpeg_binaries(),
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='YouTube Downloader',
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
