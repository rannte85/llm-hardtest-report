#!/usr/bin/env python3
from __future__ import annotations

import unittest

from jsonl_stream import JsonlEventStream


class PublicTests(unittest.TestCase):
    def test_single_record(self):
        events = []
        stream = JsonlEventStream(events.append)
        stream.feed(b'{"id":1}\n')
        self.assertEqual(events, [{"id": 1}])

    def test_multiple_records_in_one_chunk(self):
        events = []
        stream = JsonlEventStream(events.append)
        stream.feed(b'{"id":1}\n{"id":2}\n')
        self.assertEqual(events, [{"id": 1}, {"id": 2}])

    def test_blank_lines_and_crlf_are_ignored(self):
        events = []
        stream = JsonlEventStream(events.append)
        stream.feed(b'\n\r\n{"ok":true}\r\n')
        self.assertEqual(events, [{"ok": True}])

    def test_one_record_can_span_chunks(self):
        events = []
        stream = JsonlEventStream(events.append)
        stream.feed(b'{"message":"hel')
        stream.feed(b'lo"}\n')
        self.assertEqual(events, [{"message": "hello"}])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"PUBLIC: {passed}/{result.testsRun}")
    raise SystemExit(not result.wasSuccessful())
