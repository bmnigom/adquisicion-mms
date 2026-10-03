"""A release must identify the same version in Python, Windows and Inno Setup."""
import ast
import re
import unittest
from pathlib import Path

from core import __version__


ROOT = Path(__file__).resolve().parents[1]


class PackagingVersionTests(unittest.TestCase):
    def test_release_version_agrees_across_windows_and_installer_metadata(self):
        tree = ast.parse((ROOT / "packaging/version_info.txt").read_text(encoding="utf-8"))
        versions = {}
        fixed = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "StringStruct" and len(node.args) == 2:
                key, value = [ast.literal_eval(argument) for argument in node.args]
                if key in ("FileVersion", "ProductVersion"):
                    versions[key] = value
            elif node.func.id == "FixedFileInfo":
                fixed = {keyword.arg: ast.literal_eval(keyword.value) for keyword in node.keywords
                         if keyword.arg in ("filevers", "prodvers")}
        self.assertEqual(versions, {"FileVersion": __version__, "ProductVersion": __version__})
        expected_fixed = (*[int(part) for part in __version__.split(".")], 0)
        self.assertEqual(fixed, {"filevers": expected_fixed, "prodvers": expected_fixed})
        include = (ROOT / "packaging/app_version.iss").read_text(encoding="utf-8")
        match = re.search(r'^#define AppVersion "([^"\r\n]+)"$', include, flags=re.MULTILINE)
        self.assertIsNotNone(match, "El instalador carece de una versión de producto")
        self.assertEqual(match.group(1), __version__)
        installer = (ROOT / "packaging/instalador.iss").read_text(encoding="utf-8")
        self.assertIn('#include "app_version.iss"', installer)
        self.assertIn("AppVersion={#AppVersion}", installer)


if __name__ == "__main__":
    unittest.main()
