import unittest

from smilyai.tools.schema import ValidationError, validate


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = {"properties": {"level": {"type": "integer", "minimum": 0, "maximum": 100}, "label": {"type": "string", "default": "x"}}, "required": ["level"]}

    def test_validates_and_applies_defaults(self):
        self.assertEqual(validate({"level": 42}, self.schema), {"level": 42, "label": "x"})

    def test_rejects_unknown_and_out_of_range(self):
        with self.assertRaises(ValidationError):
            validate({"level": 101}, self.schema)
        with self.assertRaises(ValidationError):
            validate({"level": 10, "shell": "rm"}, self.schema)


if __name__ == "__main__":
    unittest.main()

