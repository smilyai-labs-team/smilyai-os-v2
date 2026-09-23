from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class HardwareCapabilities:
    platform: str
    raspberry_pi: bool
    gpio: bool
    camera: bool
    architecture: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HardwareBackend:
    def capabilities(self) -> HardwareCapabilities:
        raise NotImplementedError

    def gpio_read(self, pin: int) -> dict[str, Any]:
        raise RuntimeError("GPIO is unavailable")

    def gpio_write(self, pin: int, value: int) -> dict[str, Any]:
        raise RuntimeError("GPIO is unavailable")

    def camera_capture(self, path: str) -> dict[str, Any]:
        raise RuntimeError("Camera capture is unavailable")

