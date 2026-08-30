"""Exception types for the order service."""


class OrderServiceError(Exception):
    """Base class for all order service errors."""


class OrderNotFound(OrderServiceError):
    """Raised when an order id is not present in storage."""


class UnsupportedWireVersion(OrderServiceError):
    """Raised when a caller asks for a wire version the service cannot serve."""
