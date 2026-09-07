import requests
from urllib.parse import quote

from .config import WatiConfig
from .exceptions import WatiRequestError


class WatiClient:
    """Single HTTP boundary for all WATI API traffic.

    Controllers and business models should call this client instead of using
    ``requests`` directly. API endpoint construction, authentication, timeouts,
    and transport errors live here so future WATI changes are isolated.
    """

    DEFAULT_TIMEOUT = 20

    def __init__(self, env, *, timeout=None):
        self.env = env
        self.config = WatiConfig(env)
        self.timeout = timeout or self.DEFAULT_TIMEOUT

    def _request(
        self,
        method,
        path,
        *,
        params=None,
        json=None,
        data=None,
        files=None,
        timeout=None,
        allow_redirects=True,
    ):
        endpoint, _token = self.config.require_api()
        url = f"{endpoint}/{str(path or '').lstrip('/')}"
        headers = self.config.authorization_headers(json_content=json is not None and files is None)
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json,
                data=data,
                files=files,
                timeout=timeout or self.timeout,
                allow_redirects=allow_redirects,
            )
        except requests.RequestException as exc:
            raise WatiRequestError(f"Unable to reach WATI: {exc}") from exc

        if not response.ok:
            detail = (response.text or response.reason or "").strip()[:1500]
            raise WatiRequestError(
                f"WATI request failed with HTTP {response.status_code}: {detail}",
                status_code=response.status_code,
                response_text=detail,
            )
        return response

    def get(self, path, **kwargs):
        return self._request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self._request("POST", path, **kwargs)

    def send_session_message(self, whatsapp_number, text, *, local_message_id, channel_number=None):
        target = quote(str(whatsapp_number or "").strip(), safe="")
        params = {
            "messageText": text,
            "localMessageId": local_message_id,
        }
        channel = (channel_number or self.config.channel_number or "").strip()
        if channel:
            params["channelPhoneNumber"] = channel
        return self.post(
            f"api/v1/sendSessionMessage/{target}",
            params=params,
        )

    def assign_operator(self, whatsapp_number, operator_email):
        return self.post(
            "api/v1/assignOperator",
            params={
                "email": operator_email,
                "whatsappNumber": whatsapp_number,
            },
        )

    def send_interactive_buttons(self, whatsapp_number, payload):
        return self.post(
            "api/v1/sendInteractiveButtonsMessage",
            params={"whatsappNumber": whatsapp_number},
            json=payload,
            timeout=30,
        )

    def send_interactive_list(self, whatsapp_number, payload):
        return self.post(
            "api/v1/sendInteractiveListMessage",
            params={"whatsappNumber": whatsapp_number},
            json=payload,
            timeout=30,
        )
