import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from smilyai.config import ConfigStore


class ConfigTests(unittest.TestCase):
    def test_persists_and_merges(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "config.json")
            store = ConfigStore(path)
            store.update({"appearance": {"reduced_effects": True}})
            loaded = ConfigStore(path).get()
            self.assertTrue(loaded["appearance"]["reduced_effects"])
            self.assertIn("provider", loaded)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertNotIn("api_key", json.loads(path.read_text()).get("provider", {}))


if __name__ == "__main__":
    unittest.main()

