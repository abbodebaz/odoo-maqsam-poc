from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.client import WatiClient
from ..services.config import WatiConfig
from ..services.exceptions import WatiConfigurationError, WatiRequestError


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
    wati_enable_interactive_buttons = fields.Boolean(
        string="الأزرار التفاعلية في صندوق الوارد",
        config_parameter="wati_connector.enable_interactive_buttons",
        default=False,
        help="عند التفعيل يظهر زر «أزرار» لموظفي خدمة العملاء لإرسال Reply Buttons من صندوق الوارد.",
    )
    wati_enable_interactive_lists = fields.Boolean(
        string="القوائم التفاعلية في صندوق الوارد",
        config_parameter="wati_connector.enable_interactive_lists",
        default=False,
        help="عند التفعيل يظهر زر «قائمة» لموظفي خدمة العملاء لإرسال Interactive Lists من صندوق الوارد.",
    )
    wati_enable_mini_inbox = fields.Boolean(
        string="المحادثات السريعة داخل Odoo",
        config_parameter="wati_connector.enable_mini_inbox",
        default=False,
        help="إظهار زر WhatsApp في شريط Odoo لفتح نافذة محادثات سريعة بدون مغادرة الشاشة الحالية.",
    )

    @api.depends("wati_webhook_token")
    def _compute_wati_webhook_url(self):
        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        ).strip().rstrip("/")
        for record in self:
            token = (record.wati_webhook_token or "").strip()
            record.wati_webhook_url = (
                f"{base_url}/wati/webhook/{token}" if base_url and token else ""
            )

    def _normalize_wati_endpoint(self, value):
        try:
            return WatiConfig.normalize_endpoint(value)
        except WatiConfigurationError as exc:
            raise UserError(_("WATI API Endpoint يجب أن يبدأ بـ http:// أو https://")) from exc

    def _normalize_wati_token(self, value):
        return WatiConfig.normalize_token(value)

    def action_wati_test_connection(self):
        self.ensure_one()
        endpoint = self._normalize_wati_endpoint(self.wati_api_endpoint)
        token = self._normalize_wati_token(self.wati_api_token)
        if not endpoint or not token:
            raise UserError(_("أدخل WATI API Endpoint وAccess Token أولًا."))

        client = WatiClient(self.env, endpoint=endpoint, token=token)
        attempts = []
        probes = [
            ("V1", client.probe_contacts_v1),
            ("V3", client.probe_contacts_v3),
        ]

        successful_version = None
        successful_response = None

        for version, probe in probes:
            try:
                response = probe()
            except WatiRequestError as exc:
                detail = (exc.response_text or str(exc) or "").strip().replace("\n", " ")[:260]
                if exc.status_code:
                    attempts.append(f"{version}: HTTP {exc.status_code} — {detail}")
                else:
                    attempts.append(f"{version}: connection error — {detail}")
                continue
            except WatiConfigurationError as exc:
                attempts.append(f"{version}: configuration error — {exc}")
                continue

            successful_version = version
            successful_response = response
            break

        if not successful_response:
            auth_errors = [item for item in attempts if "HTTP 401" in item or "HTTP 403" in item]
            if auth_errors:
                raise UserError(
                    _(
                        "WATI لم يقبل التوثيق على المسارات التي اختبرناها. تأكد أن API Endpoint هو رابط الحساب نفسه وأن Access Token صحيح. يمكنك لصق التوكن مع أو بدون كلمة Bearer.\n\nنتائج الاختبار:\n%s"
                    )
                    % "\n".join(attempts)
                )
            raise UserError(
                _(
                    "لم نجد مسار API صالح على هذا WATI Endpoint. انسخ API Endpoint من WATI → API Docs بدون أي /api/... إضافية.\n\nنتائج الاختبار:\n%s"
                )
                % "\n".join(attempts)
            )

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
