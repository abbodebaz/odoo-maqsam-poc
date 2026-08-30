from urllib.parse import quote

import requests

from odoo import _, models
from odoo.exceptions import UserError


class WatiConversationSendFix(models.Model):
    _inherit = "wati.conversation"

    def send_session_message(self, text):
        """Send through WATI without mutating Odoo after the external call.

        Odoo may retry a request when a concurrent transaction raises a
        serialization failure. Any database write after the WATI HTTP call can
        therefore cause the external side effect to run more than once. WATI
        webhooks remain the authoritative source for outbound messages and
        their SENT/DELIVERED/READ state, so this method intentionally performs
        no ORM write after the API call succeeds.
        """
        self.ensure_one()
        target = (self.wa_id or "").strip()
        text = (text or "").strip()

        if not target:
            raise UserError(_("لا يوجد رقم WhatsApp لهذه المحادثة."))
        if not text:
            raise UserError(_("اكتب الرسالة أولًا."))
        if len(text) > 4096:
            raise UserError(_("الرسالة أطول من الحد المسموح في WhatsApp (4096 حرفًا)."))

        params = self.env["ir.config_parameter"].sudo()
        endpoint = (params.get_param("wati_connector.api_endpoint") or "").strip().rstrip("/")
        token = (params.get_param("wati_connector.api_token") or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()

        if not endpoint or not token:
            raise UserError(_("إعدادات WATI API غير مكتملة. راجع Settings → WATI WhatsApp."))

        url = f"{endpoint}/api/v1/sendSessionMessage/{quote(target, safe='')}"
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                params={"messageText": text},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise UserError(_("تعذر إرسال رسالة WhatsApp: %s") % exc) from exc

        if not response.ok:
            detail = (response.text or response.reason or "").strip()[:500]
            if response.status_code in (400, 409) and "session" in detail.lower():
                raise UserError(
                    _(
                        "لا يمكن إرسال رسالة عادية لأن جلسة WhatsApp غير مفتوحة. "
                        "سنستخدم Template لهذه الحالة لاحقًا.\n\n%s"
                    )
                    % detail
                )
            raise UserError(_("WATI رفض إرسال الرسالة (%s): %s") % (response.status_code, detail))

        return True
