import tempfile
import unittest
from pathlib import Path

from smilyai.tools.files import FileTools, PathSandbox


class PathAndFileTests(unittest.TestCase):
    def test_blocks_escape_and_symlink(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            sandbox = PathSandbox([root])
            with self.assertRaises(PermissionError):
                sandbox.resolve(outside)
            Path(root, "link").symlink_to(outside)
            with self.assertRaises(PermissionError):
                sandbox.resolve(str(Path(root, "link", "data")))

    def test_end_to_end_folder_creation(self):
        with tempfile.TemporaryDirectory() as root:
            tools = FileTools(PathSandbox([root]))
            destination = str(Path(root, "SmilyTest"))
            result = tools.create_folder(destination)
            self.assertTrue(Path(result["path"]).is_dir())
            listing = tools.list_files(root)
            self.assertEqual(listing["items"][0]["name"], "SmilyTest")


if __name__ == "__main__":
    unittest.main()

