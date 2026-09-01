# JSONL event stream incident

`JsonlEventStream` receives arbitrary byte chunks from one ordered network stream and
delivers JSON object records to `on_event`. Production occasionally corrupts or loses
records when a chunk ends in the middle of a JSON line.

The public contract is:

- `feed(chunk)` accepts bytes-like input and may receive any number of complete or
  partial newline-delimited records;
- empty lines are ignored and `\r\n` is accepted;
- `close()` processes one final non-empty record without a trailing newline and is
  idempotent;
- each decoded JSON value must be an object;
- malformed UTF-8, malformed JSON, non-object JSON, and frames larger than
  `max_frame_bytes` call `on_error(exception)` exactly once for that frame, discard only
  through its newline boundary, and allow later frames to continue;
- the size limit counts JSON frame bytes, not Unicode characters; the optional `\r`
  in a CRLF delimiter is excluded;
- event and error callbacks are delivered serially in wire order. A callback may call
  `feed()` again; records already framed by the outer call remain ahead of reentrant
  records and callback recursion must not grow;
- `feed()` after `close()` raises `RuntimeError`.

`on_error` defaults to a no-op. Exceptions raised by user callbacks are outside this
incident's recovery contract and may propagate.

Run the visible checks with:

```bash
python3 run_tests.py
```

Keep the implementation dependency-free and do not change this file, `run_tests.py`, or
`operator_note.txt`.
