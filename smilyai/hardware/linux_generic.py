from __future__ import annotations

import platform

from .base import HardwareBackend, HardwareCapabilities


class LinuxGenericHardware(HardwareBackend):
    def capabilities(self) -> HardwareCapabilities:
        return HardwareCapabilities("linux-generic", False, False, False, platform.machine())

