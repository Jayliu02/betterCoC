from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

from .adb import AdbDevice
from .errors import CaptureError, ConfigError
from .image import load_image


class Capture(Protocol):
    description: str

    def grab(self) -> np.ndarray: ...

    def close(self) -> None: ...


class StaticCapture:
    def __init__(self, image: np.ndarray, description: str = "static") -> None:
        self.image = image
        self.description = description

    def grab(self) -> np.ndarray:
        return self.image.copy()

    def close(self) -> None:
        return None


class FolderCapture:
    def __init__(self, folder: str | Path, loop: bool = True) -> None:
        self.folder = Path(folder).resolve()
        if not self.folder.exists():
            raise ConfigError(f"截图目录不存在: {self.folder}")
        if self.folder.is_file():
            self.files = [self.folder]
        else:
            extensions = {".png", ".jpg", ".jpeg", ".bmp"}
            self.files = sorted(
                path
                for path in self.folder.iterdir()
                if path.is_file() and path.suffix.lower() in extensions
            )
        if not self.files:
            raise ConfigError(f"截图目录中没有图片: {self.folder}")
        self.loop = loop
        self.index = 0
        self.description = f"folder:{self.folder}"

    def grab(self) -> np.ndarray:
        if self.index >= len(self.files):
            if not self.loop:
                self.index = len(self.files) - 1
            else:
                self.index = 0
        path = self.files[self.index]
        self.index += 1
        return load_image(path)

    def close(self) -> None:
        return None


class AdbCapture:
    def __init__(self, device: AdbDevice) -> None:
        self.device = device
        self.description = f"adb:{device.serial or 'auto'}"

    def grab(self) -> np.ndarray:
        return self.device.screencap()

    def close(self) -> None:
        return None


def create_capture(
    backend: str,
    device: AdbDevice | None = None,
    folder: str | Path | None = None,
    loop: bool = True,
    image_path: str | Path | None = None,
) -> Capture:
    if image_path is not None:
        return StaticCapture(load_image(image_path), description=str(image_path))
    if backend == "adb":
        if device is None:
            raise CaptureError("adb 截图需要 AdbDevice")
        return AdbCapture(device)
    if backend == "folder":
        if folder is None:
            raise ConfigError("capture.backend=folder 但未设置 capture.folder")
        return FolderCapture(folder, loop=loop)
    raise ConfigError(f"未知截图后端: {backend}")
