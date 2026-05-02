# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


project_root = Path(globals().get("SPECPATH", Path.cwd())).resolve()

datas = [
    (str(project_root / "assets" / "app_icon.ico"), "assets"),
    (str(project_root / "assets" / "app_icon.png"), "assets"),
]
binaries = []
hiddenimports = []

for package_name in ("faster_whisper", "ctranslate2", "av", "tokenizers"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports


a = Analysis(
    ["app.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "bandit",
        "pip_audit",
        "pre_commit",
        "pytest",
        "_pytest",
        "openwakeword",
        "sklearn",
        "scipy",
        "joblib",
        "threadpoolctl",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="jarvis_local",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(project_root / "assets" / "app_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="JARVIS Local",
)
