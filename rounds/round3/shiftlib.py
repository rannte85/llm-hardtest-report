# shiftlib.py — work-shift calculation library (currently 12/15 tests pass)

def parse(s):
    h, m = s.split(":")
    h, m = int(h), int(m)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"bad time: {s}")
    return h * 60 + m

def normalize(entry):
    """entry: {"start": "HH:MM", "end": "HH:MM", "overnight": bool}
    Return a ``(start, end)`` tuple expressed in minutes."""
    s = parse(entry["start"])
    e = parse(entry["end"])
    return (s, e)

def span(iv):
    """Return the length, in minutes, of a normalized interval."""
    s, e = iv
    return e - s

def is_reversed(entry):
    """Detect a reversed same-day shift where ``start > end``."""
    return span(normalize(entry)) < 0

def longest(entries):
    """Return the valid entry with the longest span."""
    return max(entries, key=lambda x: span(normalize(x)))

def within(entry, t):
    """Return whether time ``t`` lies inside the entry interval."""
    s, e = normalize(entry)
    return s <= parse(t) < s + span((s, e))

def total_minutes(entries):
    return sum(span(normalize(x)) for x in entries)
