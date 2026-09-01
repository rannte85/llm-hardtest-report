#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from secure_extract import safe_extract


def make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)


class PublicTests(unittest.TestCase):
    def test_regular_nested_files_are_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "package.zip"
            destination = root / "out"
            make_zip(archive, [("package.json", "{}"), ("lib/main.py", "ok = True")])
            extracted = safe_extract(archive, destination)
            self.assertEqual(extracted, ["lib/main.py", "package.json"])
            self.assertEqual((destination / "lib/main.py").read_text(), "ok = True")

    def test_explicit_directory_entries_are_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "package.zip"
            destination = root / "out"
            make_zip(archive, [("assets/", b""), ("assets/icon.txt", "icon")])
            self.assertEqual(safe_extract(archive, destination), ["assets/icon.txt"])

    def test_parent_traversal_is_rejected_without_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "package.zip"
            destination = root / "tenant"
            outside = root / "shared.txt"
            make_zip(archive, [("../shared.txt", "owned")])
            with self.assertRaises(ValueError):
                safe_extract(archive, destination)
            self.assertFalse(outside.exists())

    def test_absolute_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "package.zip"
            make_zip(archive, [("/absolute.txt", "owned")])
            with self.assertRaises(ValueError):
                safe_extract(archive, root / "out")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"PUBLIC: {passed}/{result.testsRun}")
    raise SystemExit(not result.wasSuccessful())
