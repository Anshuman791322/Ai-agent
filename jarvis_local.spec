# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs


project_root = Path(globals().get("SPECPATH", Path.cwd())).resolve()

datas = [
    (str(project_root / "assets"), "assets"),
]
binaries = []
hiddenimports = [
    "openwakeword.model",
    "openwakeword.utils",
    "openwakeword.vad",
    "onnxruntime",
    "onnxruntime.capi.onnxruntime_inference_collection",
    "onnxruntime.capi.onnxruntime_pybind11_state",
]

for package_name in ("faster_whisper", "ctranslate2", "av", "tokenizers", "openwakeword", "onnxruntime"):
    if package_name in {"openwakeword", "onnxruntime"}:
        continue
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

binaries += collect_dynamic_libs("onnxruntime")


a = Analysis(
    ["app.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
