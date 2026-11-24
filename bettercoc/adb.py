from __future__ import annotations

import subprocess
import time

import cv2
import numpy as np

from .errors import CaptureError, DeviceError


class AdbDevice:
    def __init__(
        self,
        adb_path: str = "adb",
        serial: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.adb_path = adb_path
        self.serial = serial
        self.timeout = timeout
        self._resolved = False

    def _command(self, args: list[str]) -> list[str]:
        command = [self.adb_path]
        if self.serial:
            command.extend(["-s", self.serial])
        command.extend(args)
        return command

    def _run(
        self,
        args: list[str],
        timeout: float | None = None,
        use_serial: bool = True,
    ) -> subprocess.CompletedProcess:
        command = [self.adb_path]
        if use_serial and self.serial:
            command.extend(["-s", self.serial])
        command.extend(args)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=timeout or self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise DeviceError(
                f"找不到 adb: {self.adb_path}。安装 Android Platform Tools，或设置 device.adb_path。"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise DeviceError(f"adb 命令超时: {' '.join(args)}") from exc
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise DeviceError(f"adb 命令失败: {' '.join(args)}\n{message}")
        return result

    def _list_devices(self) -> list[str]:
        result = self._run(["devices"], use_serial=False)
        output = result.stdout.decode("utf-8", errors="replace")
        devices = []
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    def resolve(self) -> str:
        if self._resolved and self.serial:
            return self.serial
        devices = self._list_devices()
        if self.serial and ":" in self.serial and self.serial not in devices:
            try:
                self._run(["connect", self.serial], use_serial=False)
            except DeviceError:
                pass
            devices = self._list_devices()
        if not devices:
            raise DeviceError(
                "没有找到可用的 Android 设备。启动模拟器并开启 ADB 调试，"
                "或执行 adb connect 127.0.0.1:16384。"
            )
        if self.serial is None:
            self.serial = devices[0]
        elif self.serial not in devices:
            raise DeviceError(f"设备 {self.serial} 不在线，当前设备: {', '.join(devices)}")
        self._resolved = True
        return self.serial

    def screencap(self) -> np.ndarray:
        self.resolve()
        try:
            result = subprocess.run(
                self._command(["exec-out", "screencap", "-p"]),
                capture_output=True,
                timeout=max(self.timeout, 30.0),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CaptureError("adb 截图超时") from exc
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise CaptureError(f"adb 截图失败: {message}")
        buffer = np.frombuffer(result.stdout, dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image is None:
            raise CaptureError("adb 截图解码失败，尝试改用 capture.backend=folder 调试")
        return image

    def tap(self, x: int, y: int) -> None:
        self.resolve()
        self._run(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.resolve()
        self._run(
            [
                "shell",
                "input",
                "swipe",
                str(x1),
                str(y1),
                str(x2),
                str(y2),
                str(duration_ms),
            ]
        )

    def key(self, code: int | str) -> None:
        self.resolve()
        self._run(["shell", "input", "keyevent", str(code)])

    def scroll(self, x: int, y: int, vertical: int) -> None:
        self.resolve()
        self._run(
            [
                "shell",
                "input",
                "scroll",
                str(x),
                str(y),
                "--axis",
                f"VSCROLL,{vertical}",
            ]
        )

    def force_stop(self, package: str) -> None:
        self.resolve()
        self._run(["shell", "am", "force-stop", package])

    def start_app(self, package: str) -> None:
        self.resolve()
        self._run(
            [
                "shell",
                "monkey",
                "-p",
                package,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ]
        )

    def pinch(
        self,
        center_x: int = 540,
        center_y: int = 960,
        start_radius: int = 260,
        end_radius: int = 40,
        steps: int = 12,
        device: str = "/dev/input/event4",
    ) -> None:
        self.resolve()
        events: list[str] = []

        def emit(kind: int, code: int, value: int) -> None:
            events.append(f"sendevent {device} {kind} {code} {value}")

        left = center_x - start_radius
        right = center_x + start_radius
        emit(3, 47, 0)
        emit(3, 57, 100)
        emit(3, 53, left)
        emit(3, 54, center_y)
        emit(3, 47, 1)
        emit(3, 57, 101)
        emit(3, 53, right)
        emit(3, 54, center_y)
        emit(1, 330, 1)
        emit(0, 0, 0)
        for _ in range(steps):
            left += max(1, (start_radius - end_radius) // steps)
            right -= max(1, (start_radius - end_radius) // steps)
            emit(3, 47, 0)
            emit(3, 53, left)
            emit(3, 54, center_y)
            emit(3, 47, 1)
            emit(3, 53, right)
            emit(3, 54, center_y)
            emit(0, 0, 0)
        emit(3, 47, 0)
        emit(3, 57, -1)
        emit(3, 47, 1)
        emit(3, 57, -1)
        emit(1, 330, 0)
        emit(0, 0, 0)
        self._run(["shell", "; ".join(events)])

    def tap_async(self, x: int, y: int) -> None:
        self.tap(x, y)
        time.sleep(0.01)

    def pull_text(self, command: str) -> str:
        result = self._run(["shell", command])
        return result.stdout.decode("utf-8", errors="replace").strip()
