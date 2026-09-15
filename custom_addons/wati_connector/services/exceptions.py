class WatiError(Exception):
    """Base exception for WATI connector service failures."""


class WatiConfigurationError(WatiError):
    """Raised when required WATI configuration is missing or invalid."""


class WatiRequestError(WatiError):
    """Raised when WATI rejects a request or cannot be reached."""

    def __init__(self, message, *, status_code=None, response_text=""):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text
