import unittest

from smilyai.permissions import PermissionEngine, Risk


class PermissionTests(unittest.TestCase):
    def test_low_risk_is_immediate(self):
        self.assertTrue(PermissionEngine().evaluate("info", {}, Risk.LOW, "read")["allowed"])

    def test_confirmation_is_single_use(self):
        engine = PermissionEngine()
        decision = engine.evaluate("delete_file", {"path": "/tmp/x"}, Risk.CONFIRM, "trash x")
        token = decision["confirmation"]["token"]
        self.assertIsNotNone(engine.consume(token, True))
        self.assertIsNone(engine.consume(token, True))

    def test_admin_requires_phrase(self):
        engine = PermissionEngine()
        decision = engine.evaluate("restart", {}, Risk.ADMIN, "restart")
        token = decision["confirmation"]["token"]
        self.assertIsNone(engine.consume(token, True, "wrong"))


if __name__ == "__main__":
    unittest.main()

