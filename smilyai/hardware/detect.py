from __future__ import annotations

from pathlib import Path

from .base import HardwareBackend
from .linux_generic import LinuxGenericHardware
from .raspberry_pi import RaspberryPiHardware


def detect_hardware() -> HardwareBackend:
    model = Path("/proc/device-tree/model")
    try:
        if "Raspberry Pi" in model.read_text(errors="ignore"):
            return RaspberryPiHardware()
    except OSError:
        pass
    return LinuxGenericHardware()

