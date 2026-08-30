import requests

from odoo import _, api, fields, models
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
        help="Bearer / Access Token الخاص بـWATI. يمكنك لصق التوكن فقط أو القيمة التي تبدأ بـ Bearer.",
    )
    wati_webhook_token = fields.Char(
        string="Webhook Secret Token",
        config_parameter="wati_connector.webhook_token",
        help="سر مستقل لحماية Webhook بين WATI وOdoo. لا تستخدم WATI API Token هنا.",
    )
    wati_webhook_url = fields.Char(
        string="Webhook URL",
        compute="_compute_wati_webhook_url",
        help="انسخ هذا الرابط كاملًا كما هو إلى WATI Webhooks.",
    )

    @api.depends("wati_webhook_token")
    def _compute_wati_webhook_url(self):
        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url")
            or "https://odoo-production-790f.up.railway.app"
        ).strip().rstrip("/")
        for record in self:
            token = (record.wati_webhook_token or "").strip()
            record.wati_webhook_url = (
                f"{base_url}/wati/webhook/{token}" if token else ""
            )

    def _normalize_wati_endpoint(self, value):
        endpoint = (value or "").strip().rstrip("/")
        if not endpoint:
            return ""
        if not endpoint.startswith(("https://", "http://")):
            raise UserError(_("WATI API Endpoint يجب أن يبدأ بـ https://"))

        # Users sometimes paste a complete API URL from WATI instead of the tenant base URL.
        # Keep the tenant id/path (e.g. /310263) and strip only the versioned /api/... suffix.
        lower = endpoint.lower()
        api_pos = lower.find("/api/")
        if api_pos != -1:
            endpoint = endpoint[:api_pos].rstrip("/")
        return endpoint

    def _normalize_wati_token(self, value):
        token = (value or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        return token

    def _wati_headers(self, token):
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def action_wati_test_connection(self):
        self.ensure_one()
        endpoint = self._normalize_wati_endpoint(self.wati_api_endpoint)
        token = self._normalize_wati_token(self.wati_api_token)
        if not endpoint or not token:
            raise UserError(_("أدخل WATI API Endpoint وAccess Token أولًا."))

        headers = self._wati_headers(token)
        attempts = []

        # Classic V1 is first because many existing WATI tenants (and the user's proven n8n flow)
        # use tenant URLs such as /<tenant-id>/api/v1/.... V3 is kept as discovery fallback.
        probes = [
            (
                "V1",
                f"{endpoint}/api/v1/getContacts",
                {"pageSize": 1, "pageNumber": 1},
            ),
            (
                "V3",
                f"{endpoint}/api/ext/v3/contacts/count",
                {},
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

            detail = (response.text or response.reason or "").strip().replace("\n", " ")[:260]
            if response.ok:
                successful_version = version
                successful_response = response
                break

            attempts.append(f"{version}: HTTP {response.status_code} — {detail}")
            # Do not stop after V3/V1 auth errors: older tokens can be accepted by one API family
            # and rejected by another. We only report auth failure after trying both families.

        if not successful_response:
            auth_errors = [item for item in attempts if "HTTP 401" in item or "HTTP 403" in item]
            if auth_errors:
                raise UserError(
                    _(
                        "WATI لم يقبل التوثيق على المسارات التي اختبرناها. تأكد أن API Endpoint هو رابط الحساب نفسه وأن Access Token هو نفسه المستخدم في n8n. يمكنك لصق التوكن مع أو بدون كلمة Bearer.\n\nنتائج الاختبار:\n%s"
                    )
                    % "\n".join(attempts)
                )
            raise UserError(
                _(
                    "لم نجد مسار API صالح على هذا WATI Endpoint. انسخ API Endpoint من WATI → API Docs بدون أي /api/... إضافية.\n\nنتائج الاختبار:\n%s"
                )
                % "\n".join(attempts)
            )

        # Persist normalized values automatically so future calls use exactly one Bearer prefix.
        self.wati_api_endpoint = endpoint
        self.wati_api_token = token

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
            message += _(" — تم اعتماد V1 لهذا الحساب.")

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
