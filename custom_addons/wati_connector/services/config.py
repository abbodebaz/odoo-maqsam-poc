from urllib.parse import urlsplit, urlunsplit

from .exceptions import WatiConfigurationError


class WatiConfig:
    """Centralized access to WATI connector configuration.

    This class intentionally owns normalization of endpoint/token values so the
    rest of the connector never reimplements configuration parsing.
    """

    PARAM_ENDPOINT = "wati_connector.api_endpoint"
    PARAM_TOKEN = "wati_connector.api_token"
    PARAM_CHANNEL = "wati_connector.channel_number"
    PARAM_WEBHOOK_TOKEN = "wati_connector.webhook_token"

    def __init__(self, env):
        self.env = env
        self._params = env["ir.config_parameter"].sudo()

    @staticmethod
    def normalize_endpoint(value):
        endpoint = (value or "").strip().rstrip("/")
        if not endpoint:
            return ""
        if not endpoint.startswith(("https://", "http://")):
            raise WatiConfigurationError("WATI API Endpoint must start with http:// or https://")

        parts = urlsplit(endpoint)
        path = parts.path or ""
        api_pos = path.lower().find("/api/")
        if api_pos != -1:
            path = path[:api_pos]
        normalized = urlunsplit((parts.scheme, parts.netloc, path.rstrip("/"), "", ""))
        return normalized.rstrip("/")

    @staticmethod
    def normalize_token(value):
        token = (value or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        return token

    @property
    def endpoint(self):
        return self.normalize_endpoint(self._params.get_param(self.PARAM_ENDPOINT) or "")

    @property
    def token(self):
        return self.normalize_token(self._params.get_param(self.PARAM_TOKEN) or "")

    @property
    def channel_number(self):
        return (self._params.get_param(self.PARAM_CHANNEL) or "").strip()

    @property
    def webhook_token(self):
        return (self._params.get_param(self.PARAM_WEBHOOK_TOKEN) or "").strip()

    @property
    def is_api_configured(self):
        """Return whether the connector has a usable API endpoint and token.

        Readiness checks in the UI should never need to duplicate configuration
        parsing or raise on a malformed endpoint. A malformed endpoint simply
        means the API is not ready yet.
        """
        try:
            return bool(self.endpoint and self.token)
        except WatiConfigurationError:
            return False

    def require_api(self):
        endpoint = self.endpoint
        token = self.token
        if not endpoint or not token:
            raise WatiConfigurationError("WATI API configuration is incomplete")
        return endpoint, token

    def authorization_headers(self, *, json_content=False):
        _, token = self.require_api()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers
