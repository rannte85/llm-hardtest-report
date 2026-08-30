"""Clock indirection so that retry timing can be driven deterministically."""

import time


class SystemClock:
    """The real clock. Used by the service unless a caller injects its own."""

    def sleep_ms(self, milliseconds):
        time.sleep(milliseconds / 1000.0)

    def now_ms(self):
        return int(time.monotonic() * 1000)
