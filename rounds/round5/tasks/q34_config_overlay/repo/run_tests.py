#!/usr/bin/env python3
from __future__ import annotations

import unittest

from config_merge import merge_config


class PublicTests(unittest.TestCase):
    def test_false_disables_an_inherited_feature(self):
        base = {"features": {"retry": True, "audit": True}}
        overlay = {"features": {"retry": False}}
        self.assertEqual(merge_config(base, overlay), {
            "features": {"retry": False, "audit": True},
        })

    def test_nested_positive_override_preserves_siblings(self):
        base = {"service": {"host": "old", "port": 443}}
        overlay = {"service": {"host": "new"}}
        self.assertEqual(merge_config(base, overlay), {
            "service": {"host": "new", "port": 443},
        })

    def test_scalar_override(self):
        self.assertEqual(
            merge_config({"region": "west"}, {"region": "east"}),
            {"region": "east"})

    def test_empty_overlay_retains_values(self):
        base = {"service": {"port": 443}}
        self.assertEqual(merge_config(base, {}), base)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"PUBLIC: {passed}/{result.testsRun}")
    raise SystemExit(not result.wasSuccessful())
