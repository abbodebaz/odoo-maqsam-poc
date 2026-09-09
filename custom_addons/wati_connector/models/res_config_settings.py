from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.client import WatiClient
from ..services.config import WatiConfig
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.feature_access import sync_feature_access_controls


_FEATURE_ACCESS_SELECTION = [
    ("all", "All users WhatsApp"),
    ("admin", "Moderators WhatsApp Only"),
]


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    wati_api_endpoint = fields.Char(
        string="WATI API Endpoint",
        config_parameter="wati_connector.api_endpoint",
        help="Copy API Endpoint Who WATI As it is, example: https://live-mt-server.wati.io/xxxxxx",
    )
    wati_api_token = fields.Char(
        string="WATI API Token",
        config_parameter="wati_connector.api_token",
        help="Bearer / Access Token ForWATI. You can paste only the token or the value starting with Bearer.",
    )
    wati_webhook_token = fields.Char(
        string="Webhook Secret Token",
        config_parameter="wati_connector.webhook_token",
        help="Independent secret to protect Webhook Between WATI AndOdoo. Do not use WATI API Token Here.",
    )
    wati_webhook_url = fields.Char(
        string="Webhook URL",
        compute="_compute_wati_webhook_url",
        help="Copy this entire link as is to WATI Webhooks.",
    )
    wati_enable_interactive_buttons = fields.Boolean(
        string="Interactive buttons in the inbox",
        config_parameter="wati_connector.enable_interactive_buttons",
        default=False,
        help="When activated, a button appears «Buttons» For customer service staff to send Reply Buttons From your inbox.",
    )
    wati_enable_interactive_lists = fields.Boolean(
        string="Interactive menus in your inbox",
        config_parameter="wati_connector.enable_interactive_lists",
        default=False,
        help="When activated, a button appears «List» For customer service staff to send Interactive Lists From your inbox.",
    )
    wati_enable_mini_inbox = fields.Boolean(
        string="Quick conversations inside Odoo",
        config_parameter="wati_connector.enable_mini_inbox",
        default=False,
        help="Show button WhatsApp In a bar Odoo Opens the Quick Chats window without leaving the current screen.",
    )

    # Workspace feature access. These are company-level policies. Individual
    # users receive the WATI role separately in Odoo access rights.
    wati_access_conversations = fields.Selection(
        _FEATURE_ACCESS_SELECTION,
        string="Conversation Log",
        config_parameter="wati_connector.access_conversations",
        default="all",
        required=True,
    )
    wati_access_messages = fields.Selection(
        _FEATURE_ACCESS_SELECTION,
        string="Message Log",
        config_parameter="wati_connector.access_messages",
        default="all",
        required=True,
    )
    wati_access_templates = fields.Selection(
        _FEATURE_ACCESS_SELECTION,
        string="Template Center",
        config_parameter="wati_connector.access_templates",
        default="admin",
        required=True,
    )
    wati_access_automation = fields.Selection(
        _FEATURE_ACCESS_SELECTION,
        string="Automation Center",
        config_parameter="wati_connector.access_automation",
        default="admin",
        required=True,
    )
    wati_access_automation_logs = fields.Selection(
        _FEATURE_ACCESS_SELECTION,
        string="Run Log",
        config_parameter="wati_connector.access_automation_logs",
        default="admin",
        required=True,
    )
    wati_access_monitor = fields.Selection(
        _FEATURE_ACCESS_SELECTION,
        string="Monitor Webhook",
        config_parameter="wati_connector.access_monitor",
        default="admin",
        required=True,
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

    @api.model
    def _sync_wati_feature_access(self):
        """Re-apply policy after module install/upgrade and settings changes."""
        return sync_feature_access_controls(self.env)

    def set_values(self):
        result = super().set_values()
        sync_feature_access_controls(self.env)
        return result

    def _normalize_wati_endpoint(self, value):
        try:
            return WatiConfig.normalize_endpoint(value)
        except WatiConfigurationError as exc:
            raise UserError(_("WATI API Endpoint Must start with http:// Or https://")) from exc

    def _normalize_wati_token(self, value):
        return WatiConfig.normalize_token(value)

    def action_wati_test_connection(self):
        self.ensure_one()
        endpoint = self._normalize_wati_endpoint(self.wati_api_endpoint)
        token = self._normalize_wati_token(self.wati_api_token)
        if not endpoint or not token:
            raise UserError(_("Enter WATI API Endpoint AndAccess Token First."))

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
                        "WATI It did not accept documentation on the paths we tested. Make sure that API Endpoint It is the link to the account itself and that Access Token True. You can paste the token with or without the word Bearer.\n\nTest results:\n%s"
                    )
                    % "\n".join(attempts)
                )
            raise UserError(
                _(
                    "We couldn’t find a path API Valid on this WATI Endpoint. Copy API Endpoint Who WATI → API Docs Without any /api/... Additional.\n\nTest results:\n%s"
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

        message = _("ContactedWATI Successfully ✅ — API %s") % successful_version
        if count is not None:
            message += _(" — Number of contacts: %s") % count
        if successful_version == "V1":
            message += _(" — has been approved V1 for this account.")

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
