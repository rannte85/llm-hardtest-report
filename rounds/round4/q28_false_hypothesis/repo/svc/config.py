"""Configuration loading for quote-svc.

Precedence, lowest to highest:

    1. ``config/service.json``   -- checked-in defaults
    2. ``config/service.env``    -- per-deployment overrides (``SVC_*``)
    3. the process environment   -- ``SVC_*``

Every key documented in README.md has a declared type; see ``SCHEMA``.
"""

import json
import os

from .errors import ConfigError

ENV_PREFIX = "SVC_"

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

DEFAULTS_PATH = os.path.join(_ROOT, "config", "service.json")
ENV_FILE_PATH = os.path.join(_ROOT, "config", "service.env")

#: Declared type of every documented configuration key.
SCHEMA = {
    "upstream_url": str,
    "timeout_ms": int,
    "max_attempts": int,
    "base_delay_ms": int,
    "backoff_max_ms": int,
}


def read_defaults(path=None):
    """Read ``config/service.json``."""
    path = path or DEFAULTS_PATH
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise ConfigError("defaults file not found: %s" % path)
    except ValueError as exc:
        raise ConfigError("defaults file is not valid JSON: %s" % exc)
    if not isinstance(data, dict):
        raise ConfigError("defaults file must contain a JSON object")
    return data


def validate(config):
    """Check that every documented key is present with its declared type."""
    for key, expected in SCHEMA.items():
        if key not in config:
            raise ConfigError("missing configuration key: %s" % key)
        if not isinstance(config[key], expected):
            raise ConfigError(
                "configuration key %r must be %s, got %r"
                % (key, expected.__name__, config[key])
            )
    return config


def read_env_file(path=None):
    """Parse a ``KEY=value`` file.

    A missing file simply means "this deployment has no overrides".
    """
    path = path or ENV_FILE_PATH
    values = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        values[key.strip()] = raw
    return values


def collect_overrides(env_file_values, environ):
    """Merge the process environment on top of the deployment env file."""
    merged = dict(env_file_values)
    for key in sorted(environ):
        if key.startswith(ENV_PREFIX):
            merged[key] = environ[key]
    return merged


def apply_overrides(config, overrides):
    """Lay ``SVC_*`` overrides on top of ``config``.

    Keys that are not part of the documented configuration are ignored, so an
    unrelated ``SVC_`` variable in the environment cannot inject new settings.
    """
    merged = dict(config)
    for raw_key, raw_value in overrides.items():
        if raw_key.startswith(ENV_PREFIX):
            key = raw_key[len(ENV_PREFIX):].lower()
        else:
            key = raw_key.lower()
        if key not in merged:
            continue
        merged[key] = raw_value
    return merged


def load_config(defaults_path=None, env_file=None, environ=None):
    """Build the effective configuration mapping."""
    defaults = read_defaults(defaults_path)
    validate(defaults)
    if environ is None:
        environ = os.environ
    overrides = collect_overrides(read_env_file(env_file), environ)
    return apply_overrides(defaults, overrides)


def explain(defaults_path=None, env_file=None, environ=None):
    """Return ``[(key, effective_value, source, file_default), ...]``.

    Used by ``tools/dump_config.py``.
    """
    defaults = read_defaults(defaults_path)
    if environ is None:
        environ = os.environ
    file_values = read_env_file(env_file)
    process_values = {k: v for k, v in environ.items() if k.startswith(ENV_PREFIX)}
    overrides = collect_overrides(file_values, process_values)
    effective = apply_overrides(defaults, overrides)

    rows = []
    for key in sorted(effective):
        env_key = ENV_PREFIX + key.upper()
        if env_key in process_values:
            source = "process env (%s)" % env_key
        elif env_key in file_values:
            source = "config/service.env (%s)" % env_key
        else:
            source = "config/service.json"
        rows.append((key, effective[key], source, defaults.get(key)))
    return rows
