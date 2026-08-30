"""Configuration loading and precedence."""

from tests.harness import NO_ENV_FILE, expect_equal, expect_true
from svc.config import load_config


def test_defaults_load_from_file():
    config = load_config(env_file=NO_ENV_FILE, environ={})
    expect_equal(config["upstream_url"], "http://upstream.internal/v1/quote", "upstream_url")
    expect_equal(config["timeout_ms"], 250, "timeout_ms")
    expect_equal(config["max_attempts"], 3, "max_attempts")
    expect_equal(config["base_delay_ms"], 50, "base_delay_ms")
    expect_equal(config["backoff_max_ms"], 800, "backoff_max_ms")


def test_env_file_overrides_defaults():
    config = load_config(environ={})
    expect_equal(str(config["max_attempts"]), "10", "max_attempts")
    expect_true(
        config["upstream_url"].startswith("http://quote-api.ap-northeast-1"),
        "upstream_url comes from config/service.env")


def test_process_env_beats_env_file():
    config = load_config(environ={"SVC_MAX_ATTEMPTS": "7"})
    expect_equal(str(config["max_attempts"]), "7", "max_attempts")


def test_unknown_env_vars_are_ignored():
    config = load_config(environ={"SVC_NOT_A_SETTING": "x", "PATH": "/usr/bin"})
    expect_true("not_a_setting" not in config, "unknown SVC_ key is not injected")
    expect_true("path" not in config, "non-prefixed variables are ignored")


def test_missing_env_file_is_not_an_error():
    config = load_config(env_file=NO_ENV_FILE, environ={})
    expect_equal(config["timeout_ms"], 250, "timeout_ms falls back to the file default")
