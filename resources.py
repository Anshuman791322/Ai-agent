from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon


def resource_base_path() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    return resource_base_path().joinpath(*parts)


def load_app_icon() -> QIcon:
    for candidate in ("app_icon.ico", "app_icon.png"):
        path = resource_path("assets", candidate)
        if path.exists():
            return QIcon(str(path))
    return QIcon()
