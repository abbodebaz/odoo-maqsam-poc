import json as jsonlib
from urllib.parse import quote

import requests

from .config import WatiConfig
from .exceptions import WatiConfigurationError, WatiRequestError


class WatiClient:
    """Single HTTP boundary for all WATI API traffic.

    Controllers and business models should call this client instead of using
    ``requests`` directly. API endpoint construction, authentication, timeouts,
    and transport errors live here so future WATI changes are isolated.
    """

    DEFAULT_TIMEOUT = 20

    def __init__(self, env, *, timeout=None, endpoint=None, token=None):
        self.env = env
        self.config = WatiConfig(env)
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self._use_overrides = endpoint is not None or token is not None
        self._endpoint_override = WatiConfig.normalize_endpoint(endpoint or "") if self._use_overrides else ""
        self._token_override = WatiConfig.normalize_token(token or "") if self._use_overrides else ""

    def _credentials(self):
        if self._use_overrides:
            if not self._endpoint_override or not self._token_override:
                raise WatiConfigurationError("WATI API configuration is incomplete")
            return self._endpoint_override, self._token_override
        return self.config.require_api()

    def _headers(self, *, json_content=False):
        _endpoint, token = self._credentials()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        if json_content:
            headers["Content-Type"] = "application/json"
        return headers

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
        endpoint, _token = self._credentials()
        url = f"{endpoint}/{str(path or '').lstrip('/')}"
        headers = self._headers(json_content=json is not None and files is None)
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

    def _ensure_application_success(self, response, operation):
        """Reject HTTP-200 responses that still contain an application error.

        Some WATI endpoints can transport a structured failure inside a successful
        HTTP response. Template lifecycle operations must never be marked as
        successful until both transport and payload agree.
        """
        try:
            payload = response.json()
        except ValueError:
            return response
        if not isinstance(payload, dict):
            return response

        semantic_failure = (
            payload.get("success") is False
            or payload.get("result") is False
        )
        error = payload.get("error")
        if isinstance(error, str):
            semantic_failure = semantic_failure or bool(error.strip())
        elif error not in (None, False, {}, []):
            semantic_failure = True

        errors = payload.get("errors")
        if errors not in (None, False, "", {}, []):
            semantic_failure = True

        if semantic_failure:
            detail = jsonlib.dumps(payload, ensure_ascii=False, default=str)[:1500]
            raise WatiRequestError(
                f"WATI {operation} failed: {detail}",
                status_code=response.status_code,
                response_text=detail,
            )
        return response

    def get(self, path, **kwargs):
        return self._request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self._request("POST", path, **kwargs)

    def delete(self, path, **kwargs):
        return self._request("DELETE", path, **kwargs)

    def probe_contacts_v1(self):
        return self.get(
            "api/v1/getContacts",
            params={"pageSize": 1, "pageNumber": 1},
            timeout=20,
        )

    def probe_contacts_v3(self):
        return self.get(
            "api/ext/v3/contacts/count",
            timeout=20,
        )

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

    def send_session_file(self, whatsapp_number, *, filename, stream, mimetype, caption=""):
        target = quote(str(whatsapp_number or "").strip(), safe="")
        params = {"caption": caption} if caption else None
        return self.post(
            f"api/v1/sendSessionFile/{target}",
            params=params,
            files={"file": (filename, stream, mimetype)},
            timeout=90,
        )

    def assign_operator(self, whatsapp_number, operator_email):
        return self.post(
            "api/v1/assignOperator",
            params={
                "email": operator_email,
                "whatsappNumber": whatsapp_number,
            },
        )

    def get_message_templates(self, *, page_size=200, page_number=1):
        return self.get(
            "api/v1/getMessageTemplates",
            params={"pageSize": page_size, "pageNumber": page_number},
            timeout=25,
        )

    def create_whatsapp_template(self, payload):
        """Create a WhatsApp template through WATI's documented template endpoint."""
        response = self.post(
            "api/v1/whatsApp/templates",
            json=payload,
            timeout=45,
        )
        return self._ensure_application_success(response, "template creation")

    def delete_whatsapp_template(self, waba_id, name, language=None):
        """Delete one template language, or all languages when language is omitted."""
        safe_waba = quote(str(waba_id or "").strip(), safe="")
        safe_name = quote(str(name or "").strip(), safe="")
        path = f"api/v1/whatsApp/templates/{safe_waba}/{safe_name}"
        if language:
            path += f"/{quote(str(language).strip(), safe='')}"
        response = self.delete(path, timeout=45)
        return self._ensure_application_success(response, "template deletion")

    def send_template_messages(self, payload):
        return self.post(
            "api/v1/sendTemplateMessages",
            json=payload,
            timeout=30,
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
