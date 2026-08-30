"""quote-svc: a small pricing gateway that fans one client request out to the
upstream quote API, with retries."""

import logging

logging.getLogger("svc").addHandler(logging.NullHandler())

__all__ = ["config", "retry", "service", "http_client", "transport", "clock", "errors"]
