import logging

import requests

from odoo import fields, models

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


def _truthy_collection(value):
    """Return True only when WATI actually returned one or more invalid items."""
    if value in (None, False, "", [], {}, ()):
        return False
    return bool(value)


def _meaningful_text(value):
    if value in (None, False):
        return ""
    text = str(value).strip()
    if text.casefold() in {"", "false", "none", "null", "[]", "{}"}:
        return ""
    return text


def _wati_payload_has_hard_failure(payload):
    """Interpret WATI's v1 sendTemplateMessages response conservatively.

    Some WATI tenants return HTTP 200 together with `result: false` even though
    the request has been accepted and the message is queued/sent. Therefore a
    bare `result: false` is NOT sufficient evidence of failure.

    A response is considered an immediate API failure only when it contains
    concrete failure evidence: a non-empty error, invalid recipient/parameter
    collections, explicit `success: false`, or an explicit failed status.
    Final delivery is still determined by WATI webhooks.
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

    # Check common nested envelopes without treating a bare boolean `result`
    # as failure evidence.
    for key in ("data", "response"):
        nested = payload.get(key)
        if isinstance(nested, dict) and _wati_payload_has_hard_failure(nested):
            return True

    return False


class WatiAutomationResponseFix(models.Model):
    _inherit = "wati.automation.rule"

    def _send_template(self, record, phone, custom_params):
        """Send a template and classify HTTP 200 as accepted unless truly invalid.

        WATI documents 2xx as a successful API acceptance. Delivery/failure after
        acceptance is asynchronous and must be reconciled by webhooks.
        """
        self.ensure_one()
        Log = self.env["wati.automation.log"].sudo()

        if not self._validate_template_live(force=False, raise_error=False):
            Log.create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message=self.template_validation_message or "القالب غير صالح للإرسال.",
                )
            )
            return False

        endpoint, token, _configured_channel = self._wati_config()
        effective_channel = self._effective_channel()
        if not endpoint or not token:
            Log.create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message="إعدادات WATI API غير مكتملة.",
                )
            )
            return False

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
                        "لم يتم استدعاء WATI لأن متغيرات القالب التالية بدون قيمة: "
                        + ", ".join(filter(None, empty_params))
                        + ". اربطها بحقل Odoo أو ضع قيمة احتياطية."
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
            response = requests.post(
                f"{endpoint}/api/v1/sendTemplateMessages",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=25,
            )
        except requests.RequestException as exc:
            Log.create(
                self._log_values(
                    record,
                    "failed",
                    phone=phone,
                    error_message=f"تعذر الاتصال بـ WATI: {exc}",
                )
            )
            return False

        excerpt = (response.text or response.reason or "").strip()[:2000]
        if not response.ok:
            Log.create(
                {
                    **self._log_values(
                        record,
                        "failed",
                        phone=phone,
                        error_message=f"WATI رفض الإرسال ({response.status_code}).",
                        response_excerpt=excerpt,
                    ),
                    "broadcast_name": broadcast_name,
                    "delivery_status": "api_rejected",
                }
            )
            return False

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if _wati_payload_has_hard_failure(payload):
            summary = _error_summary(payload) if isinstance(payload, dict) else "WATI أعاد خطأ في الطلب."
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

        # Important: HTTP 200 means accepted by WATI, not delivered yet.
        # A bare `result:false` with empty validation arrays is kept as accepted
        # and delivery is reconciled later by Delivered/Read/Failed webhooks.
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
                "WATI automation %s accepted HTTP 200 despite result=false; awaiting webhook. broadcast=%s",
                self.id,
                broadcast_name,
            )
        return True
