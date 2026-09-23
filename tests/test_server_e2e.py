import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from smilyai.server import serve


class ServerEndToEndTests(unittest.TestCase):
    def test_intent_provider_validation_permission_and_execution_flow(self):
        with tempfile.TemporaryDirectory() as root:
            previous_home = os.environ.get("HOME")
            previous_state = os.environ.get("XDG_STATE_HOME")
            os.environ["HOME"] = root
            os.environ["XDG_STATE_HOME"] = str(Path(root, "state"))
            server = serve("127.0.0.1", 0, Path(root, "config.json"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urllib.request.urlopen(base + "/api/bootstrap") as response:
                    boot = json.load(response)
                token = boot["session_token"]

                created = self._ask(base, token, "Create a folder called SmilyTest in my home directory.")
                self.assertEqual(created["action"]["status"], "success")
                self.assertTrue(Path(root, "SmilyTest").is_dir())

                memory = self._ask(base, token, "What's using my memory?")
                self.assertEqual(memory["action"]["tool"], "get_memory_usage")
                self.assertGreater(memory["action"]["data"]["total"], 0)

                missing = self._ask(base, token, "Open DefinitelyMissingSmilyApp")
                self.assertFalse(missing["action"]["data"]["installed"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_state is None:
                    os.environ.pop("XDG_STATE_HOME", None)
                else:
                    os.environ["XDG_STATE_HOME"] = previous_state

    @staticmethod
    def _ask(base: str, token: str, text: str):
        request = urllib.request.Request(
            base + "/api/intent",
            data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json", "X-SmilyAI-Session": token},
        )
        with urllib.request.urlopen(request) as response:
            return json.load(response)


if __name__ == "__main__":
    unittest.main()
