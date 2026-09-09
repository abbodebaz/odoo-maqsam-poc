import logging

from odoo import _, fields, models

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from .wati_automation_guard import _extract_external_message_id
from .wati_automation_improvements import _error_summary


_logger = logging.getLogger(__name__)

_FAILED_STATUS_WORDS = {
    "failed",
    "failure",
    "error",
    "rejected",
    "undelivered",
    "expired",
}


def _meaningful_text(value):
    if value in (None, False):
        return ""
    text = str(value).strip()
    if text.casefold() in {"", "false", "none", "null", "[]", "{}"}:
        return ""
    return text


def _truthy_collection(value):
    """Return True only when WATI returned concrete failure content.

    WATI can return an ``errors`` object that is structurally non-empty while
    every nested value is empty, for example::

        {"error": "", "invalidWhatsappNumbers": [],
         "invalidCustomParameters": []}

    Treating ``bool(errors)`` as failure would create a false-negative log even
    though WATI accepted the request, so nested values are inspected recursively.
    """
    if value in (None, False, "", [], {}, ()):
        return False
    if isinstance(value, dict):
        return any(_truthy_collection(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_truthy_collection(item) for item in value)
    if isinstance(value, str):
        return bool(_meaningful_text(value))
    return bool(value)


def _wati_payload_has_hard_failure(payload):
    """Interpret WATI's template-send response conservatively.

    A successful HTTP response means API acceptance unless WATI supplies concrete
    failure evidence. Final delivery/read/failure remains asynchronous and is
    reconciled through WATI webhooks.
    """
    if not isinstance(payload, dict):
        return False

    if payload.get("success") is False:
        return True

    for key in (
        "errors",
        "invalidWhatsappNumbers",
        "invalidWhatsAppNumbers",
        "invalidCustomParameters",
        "invalidParameters",
        "failedWhatsappNumbers",
        "failedWhatsAppNumbers",
        "failedRecipients",
    ):
        if _truthy_collection(payload.get(key)):
            return True

    for key in (
        "error",
        "errorMessage",
        "error_message",
        "failedDetail",
        "reason",
    ):
        if _meaningful_text(payload.get(key)):
            return True

    for key in ("status", "statusString", "state"):
        text = _meaningful_text(payload.get(key)).casefold()
        if text in _FAILED_STATUS_WORDS:
            return True

    for key in ("data", "response", "errors"):
        nested = payload.get(key)
        if isinstance(nested, dict) and _wati_payload_has_hard_failure(nested):
            return True

    return False


class WatiAutomationResponse(models.Model):
    _inherit = "wati.automation.rule"

    def _send_template(self, record, phone, custom_params):
        """Send a template and distinguish API acceptance from final delivery."""
        self.ensure_one()
        Log = self.env["wati.automation.log"].sudo()

        if not self._validate_template_live(force=False, raise_error=False):
            Log.create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message=self.template_validation_message
                    or _("The template is not valid for sending."),
                )
            )
            return False

        client = WatiClient(self.env)
        effective_channel = self._effective_channel()

        empty_params = [
            str(item.get("name") or "").strip()
            for item in custom_params
            if not str(item.get("value") or "").strip()
        ]
        if empty_params:
            Log.create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message=(
                        _("WATI was not called because these template variables are empty: %s. ")
                        % ", ".join(filter(None, empty_params))
                        + _("Map each variable to an Odoo field or configure a fallback value.")
                    ),
                )
            )
            return False

        now_token = fields.Datetime.now().strftime("%Y%m%d%H%M%S%f")
        broadcast_name = f"odoo_auto_{self.id}_{record.id}_{now_token}"
        body = {
            "template_name": self.template_name,
            "broadcast_name": broadcast_name,
            "receivers": [
                {
                    "whatsappNumber": phone,
                    "customParams": custom_params,
                }
            ],
        }
        if effective_channel:
            body["channel_number"] = effective_channel

        try:
            response = client.send_template_messages(body)
        except WatiConfigurationError:
            Log.create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message=_("WATI API settings are incomplete."),
                )
            )
            return False
        except WatiRequestError as exc:
            detail = (exc.response_text or str(exc) or "").strip()[:2000]
            Log.create(
                {
                    **self._log_values(
                        record,
                        "failed",
                        phone=phone,
                        error_message=(
                            _("WATI rejected the request (HTTP %s).") % exc.status_code
                            if exc.status_code
                            else _("Unable to contact WATI: %s") % detail
                        ),
                        response_excerpt=detail,
                    ),
                    "broadcast_name": broadcast_name,
                    "delivery_status": "api_rejected" if exc.status_code else "transport_failed",
                }
            )
            return False

        excerpt = (response.text or response.reason or "").strip()[:2000]
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if _wati_payload_has_hard_failure(payload):
            summary = (
                _error_summary(payload)
                if isinstance(payload, dict)
                else _("WATI returned an error for the request.")
            )
            Log.create(
                {
                    **self._log_values(
                        record,
                        "failed",
                        phone=phone,
                        error_message=summary,
                        response_excerpt=excerpt,
                    ),
                    "broadcast_name": broadcast_name,
                    "delivery_status": "api_failed",
                }
            )
            return False

        external_message_id = _extract_external_message_id(payload)
        Log.create(
            {
                **self._log_values(
                    record,
                    "accepted",
                    phone=phone,
                    response_excerpt=excerpt,
                ),
                "broadcast_name": broadcast_name,
                "external_message_id": external_message_id or False,
                "delivery_status": "accepted_http_200",
            }
        )

        if isinstance(payload, dict) and payload.get("result") is False:
            _logger.info(
                "WATI automation %s accepted HTTP 2xx despite result=false; awaiting webhook. broadcast=%s",
                self.id,
                broadcast_name,
            )
        return True
