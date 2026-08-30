import requests

from odoo import _, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    wati_api_endpoint = fields.Char(
        string="WATI API Endpoint",
        config_parameter="wati_connector.api_endpoint",
        help="انسخ API Endpoint من WATI كما هو، مثال: https://live-mt-server.wati.io/xxxxxx",
    )
    wati_api_token = fields.Char(
        string="WATI API Token",
        config_parameter="wati_connector.api_token",
        help="Bearer Token الخاص بـWATI. لا يتم إرساله إلى المتصفح.",
    )
    wati_webhook_token = fields.Char(
        string="Webhook Secret Token",
        config_parameter="wati_connector.webhook_token",
        help="نص سري طويل يوضع داخل رابط Webhook لحماية الاستقبال.",
    )

    def action_wati_test_connection(self):
        self.ensure_one()
        endpoint = (self.wati_api_endpoint or "").strip().rstrip("/")
        token = (self.wati_api_token or "").strip()
        if not endpoint or not token:
            raise UserError(_("أدخل WATI API Endpoint وAPI Token أولًا."))
        if not endpoint.startswith(("https://", "http://")):
            raise UserError(_("WATI API Endpoint يجب أن يبدأ بـ https://"))

        try:
            response = requests.get(
                f"{endpoint}/api/ext/v3/contacts/count",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            raise UserError(_("تعذر الاتصال بـWATI: %s") % exc) from exc

        if not response.ok:
            detail = response.text[:500] if response.text else response.reason
            raise UserError(_("WATI رفض الاتصال (%s): %s") % (response.status_code, detail))

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        count = payload.get("count")
        if count is None and isinstance(payload.get("result"), dict):
            count = payload["result"].get("count")

        message = _("تم الاتصال بـWATI بنجاح ✅")
        if count is not None:
            message += _(" — عدد جهات الاتصال: %s") % count

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WATI"),
                "message": message,
                "type": "success",
                "sticky": False,
            },
        }
