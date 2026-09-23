from __future__ import annotations
import platform
import shutil
import subprocess
import threading
from pathlib import Path
from .base import HardwareBackend, HardwareCapabilities
from ..tools.files import PathSandbox

class RaspberryPiHardware(HardwareBackend):
    def __init__(self):
        self.camera_command = shutil.which("rpicam-still") or shutil.which("libcamera-still")
        self.requests = {}
        self.lock = threading.Lock()
        try:
            import gpiod
            self.gpiod = gpiod if hasattr(gpiod, "request_lines") else None
        except ImportError:
            self.gpiod = None

    def capabilities(self):
        return HardwareCapabilities("raspberry-pi", True,
            bool(self.gpiod and list(Path("/dev").glob("gpiochip*"))),
            bool(self.camera_command), platform.machine())

    def _line(self, pin):
        if type(pin) is not int or not 0 <= pin <= 27:
            raise ValueError("Choose a BCM GPIO number from 0 to 27")
        if not self.gpiod:
            raise RuntimeError("GPIO requires python3-libgpiod v2")
        # Pi 5 RP1 controller is not necessarily gpiochip0. Resolve by line name.
        for path in Path("/dev").glob("gpiochip*"):
            try:
                with self.gpiod.Chip(str(path)) as chip:
                    label = chip.get_info().label
                    if not any(x in label for x in ("pinctrl", "rp1", "bcm")):
                        continue
                    for offset in range(chip.get_info().num_lines):
                        if chip.get_line_info(offset).name == f"GPIO{pin}":
                            return str(path), offset
            except OSError:
                continue
        raise RuntimeError("GPIO line not found or access denied; no pin was changed")

    def gpio_read(self, pin):
        with self.lock:
            path, offset = self._line(pin)
            if pin in self.requests:
                value = self.requests[pin].get_value(offset)
            else:
                with self.gpiod.request_lines(path, consumer="smilyai", config={offset: self.gpiod.LineSettings(direction=self.gpiod.line.Direction.INPUT)}) as req:
                    value = req.get_value(offset)
        return {"pin": pin, "value": int(value == self.gpiod.line.Value.ACTIVE)}

    def gpio_write(self, pin, value):
        if type(value) is not int or value not in (0, 1):
            raise ValueError("GPIO value must be 0 or 1")
        with self.lock:
            path, offset = self._line(pin)
            output = self.gpiod.line.Value.ACTIVE if value else self.gpiod.line.Value.INACTIVE
            if pin not in self.requests:
                self.requests[pin] = self.gpiod.request_lines(path, consumer="smilyai",
                    config={offset: self.gpiod.LineSettings(direction=self.gpiod.line.Direction.OUTPUT, output_value=output)})
            else:
                self.requests[pin].set_value(offset, output)
        return {"pin": pin, "value": value, "held": "Output held while harness runs; do not use for safety-critical control"}

    def camera_capture(self, path):
        if not self.camera_command:
            raise RuntimeError("No Raspberry Pi camera tool found")
        with PathSandbox().parent(path) as (fd, name, p):
            import os
            target = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                result = subprocess.run([self.camera_command, "-n", "--timeout", "1000", "-o", f"/proc/self/fd/{target}"],
                    pass_fds=(target,), capture_output=True, timeout=15)
                if result.returncode:
                    raise RuntimeError("Camera unavailable; check device permissions")
            finally:
                os.close(target)
        return {"path": str(p)}

