import unittest

from smilyai.hardware import detect_hardware
from smilyai.tools.system import SystemTools


class SystemHardwareTests(unittest.TestCase):
    def test_system_info_and_memory(self):
        tools = SystemTools()
        self.assertGreater(tools.get_memory_usage(False)["total"], 0)
        self.assertIn("architecture", tools.get_system_info())

    def test_hardware_detection_is_graceful(self):
        caps = detect_hardware().capabilities().to_dict()
        self.assertIn(caps["platform"], {"linux-generic", "raspberry-pi"})
        self.assertIsInstance(caps["gpio"], bool)


if __name__ == "__main__":
    unittest.main()
