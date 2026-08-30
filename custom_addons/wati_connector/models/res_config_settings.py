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
        help="Bearer / Access Token الخاص بـWATI. لا يتم إرساله إلى المتصفح.",
    )
    wati_webhook_token = fields.Char(
        string="Webhook Secret Token",
        config_parameter="wati_connector.webhook_token",
        help="نص سري طويل يوضع داخل رابط Webhook لحماية الاستقبال.",
    )

    def _normalize_wati_endpoint(self, value):
        endpoint = (value or "").strip().rstrip("/")
        if not endpoint:
            return ""
        if not endpoint.startswith(("https://", "http://")):
            raise UserError(_("WATI API Endpoint يجب أن يبدأ بـ https://"))

        # Users sometimes paste a complete API URL from WATI instead of the tenant base URL.
        # Keep only the tenant root before /api/ so our connector can append the proper versioned route.
        lower = endpoint.lower()
        api_pos = lower.find("/api/")
        if api_pos != -1:
            endpoint = endpoint[:api_pos].rstrip("/")
        return endpoint

    def _wati_headers(self, token):
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def action_wati_test_connection(self):
        self.ensure_one()
        endpoint = self._normalize_wati_endpoint(self.wati_api_endpoint)
        token = (self.wati_api_token or "").strip()
        if not endpoint or not token:
            raise UserError(_("أدخل WATI API Endpoint وAccess Token أولًا."))

        headers = self._wati_headers(token)
        attempts = []

        # Prefer the current V3 API. Some WATI tenants still expose classic V1 routes only,
        # so fall back to V1 for connection discovery instead of treating a V3 404 as bad credentials.
        probes = [
            (
                "V3",
                f"{endpoint}/api/ext/v3/contacts/count",
                {},
            ),
            (
                "V1",
                f"{endpoint}/api/v1/getContacts",
                {"pageSize": 1, "pageNumber": 1},
            ),
        ]

        successful_version = None
        successful_response = None

        for version, url, params in probes:
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=20,
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                attempts.append(f"{version}: connection error — {exc}")
                continue

            if response.ok:
                successful_version = version
                successful_response = response
                break

            detail = (response.text or response.reason or "").strip().replace("\n", " ")[:220]
            attempts.append(f"{version}: HTTP {response.status_code} — {detail}")

            # 401/403 indicates credentials/permissions, so another API version will not fix it.
            if response.status_code in (401, 403):
                raise UserError(
                    _("WATI رفض التوثيق (%s). تأكد من Access Token وصلاحياته. التفاصيل: %s")
                    % (response.status_code, detail)
                )

        if not successful_response:
            raise UserError(
                _(
                    "لم نجد مسار API صالح على هذا WATI Endpoint. جرّب نسخ API Endpoint من WATI → API Docs بدون أي /api/... إضافية.\n\nنتائج الاختبار:\n%s"
                )
                % "\n".join(attempts)
            )

        # Persist the normalized endpoint automatically so future calls use the clean tenant root.
        self.wati_api_endpoint = endpoint

        try:
            payload = successful_response.json()
        except ValueError:
            payload = {}

        count = payload.get("count") if isinstance(payload, dict) else None
        if count is None and isinstance(payload, dict) and isinstance(payload.get("result"), dict):
            count = payload["result"].get("count")

        message = _("تم الاتصال بـWATI بنجاح ✅ — API %s") % successful_version
        if count is not None:
            message += _(" — عدد جهات الاتصال: %s") % count
        if successful_version == "V1":
            message += _(" — حسابك يجيب على V1؛ سنستخدم المسارات المتاحة لحسابك تلقائيًا.")

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WATI"),
                "message": message,
                "type": "success",
                "sticky": True,
            },
        }
