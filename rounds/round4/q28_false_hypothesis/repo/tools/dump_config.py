#!/usr/bin/env python3
"""Print the effective configuration and where each value came from.

    python3 tools/dump_config.py

Values are printed as JSON so that the wire form is unambiguous.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from svc import config as config_module  # noqa: E402


def render(value):
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)


def main(argv):
    rows = config_module.explain()

    print("defaults : %s" % os.path.relpath(config_module.DEFAULTS_PATH, ROOT))
    print("env file : %s" % os.path.relpath(config_module.ENV_FILE_PATH, ROOT))
    print()

    widths = (18, 56, 8, 40)
    header = ("key", "effective value", "python", "source")
    print("".join(text.ljust(width) for text, width in zip(header, widths)))
    print("-" * sum(widths))
    for key, value, source, file_default in rows:
        print("".join(text.ljust(width) for text, width in zip(
            (key, render(value), type(value).__name__, source), widths)))
        if source != "config/service.json":
            print("".join(text.ljust(width) for text, width in zip(
                ("", "(file default %s)" % render(file_default),
                 type(file_default).__name__, ""), widths)))
    print("-" * sum(widths))
    print()
    print("declared types (svc/config.py SCHEMA):")
    for key in sorted(config_module.SCHEMA):
        print("    %-18s %s" % (key, config_module.SCHEMA[key].__name__))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
