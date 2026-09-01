"""Naive JSONL event stream with a production chunk-boundary bug."""

from __future__ import annotations

import json


class JsonlEventStream:
    def __init__(self, on_event, on_error=None, max_frame_bytes=65536):
        self._on_event = on_event
        self._on_error = on_error or (lambda error: None)
        self._max_frame_bytes = max_frame_bytes
        self._closed = False

    def feed(self, chunk):
        """Decode each received chunk as if it contained complete JSONL records."""
        if self._closed:
            raise RuntimeError("stream is closed")
        for line in bytes(chunk).decode("utf-8").splitlines():
            if line.strip():
                self._on_event(json.loads(line))

    def close(self):
        self._closed = True
