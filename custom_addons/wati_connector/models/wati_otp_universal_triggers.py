import hmac
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_ALLOWED_SOURCES = {
    "hook",
    "server_action",
    "automation",
    "portal",
    "api",
    "webhook",
    "python",
    "website_form",
}


class WatiOtpFlowUniversalTriggers(models.Model):
    _inherit = "wati.otp.flow"

    integration_secret = fields.Char(
        string="Integration secret",
        default=lambda self: secrets.token_urlsafe(32),
        copy=False,
        groups="base.group_system",
        help="Secret used by external API, webhook, and website/form entry points.",
    )
    api_enabled = fields.Boolean(
        string="API endpoint enabled",
        default=False,
        help="Allow an external system to request OTPs through the authenticated HTTP API endpoint.",
    )
    webhook_enabled = fields.Boolean(
        string="Webhook endpoint enabled",
        default=False,
        help="Allow an external webhook to request an OTP for this flow.",
    )
    website_form_enabled = fields.Boolean(
        string="Website / form endpoint enabled",
        default=False,
        help="Allow a website or external form to request an OTP using the protected form endpoint.",
    )
    portal_entry_enabled = fields.Boolean(
        string="Portal entry enabled",
        default=True,
        help="Allow authenticated portal/internal users with access to the record to request an OTP through the generic portal endpoint.",
    )
    universal_server_action_id = fields.Many2one(
        "ir.actions.server",
        string="Reusable server action",
        readonly=True,
        copy=False,
        ondelete="set null",
        help="Reusable server action created by OTP Bridge for custom Odoo workflows.",
    )
    api_request_url = fields.Char(string="API request URL", compute="_compute_entry_point_urls")
    webhook_request_url = fields.Char(string="Webhook request URL", compute="_compute_entry_point_urls")
    website_form_request_url = fields.Char(
        string="Website / form request URL", compute="_compute_entry_point_urls"
    )
    portal_request_url_pattern = fields.Char(
        string="Portal request URL", compute="_compute_entry_point_urls"
    )
    python_hook_example = fields.Char(string="Python hook", compute="_compute_entry_point_urls")
    automation_hook_example = fields.Char(
        string="Automated Action hook", compute="_compute_entry_point_urls"
    )

    @api.depends("technical_key")
    def _compute_entry_point_urls(self):
        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url", "") or ""
        ).rstrip("/")
        for flow in self:
            key = flow.technical_key or "FLOW_KEY"
            flow.api_request_url = f"{base_url}/wati/otp/v1/api/{key}/request"
            flow.webhook_request_url = f"{base_url}/wati/otp/v1/webhook/{key}"
            flow.website_form_request_url = f"{base_url}/wati/otp/v1/form/{key}/request"
            flow.portal_request_url_pattern = (
                f"{base_url}/wati/otp/portal/{key}/request/<record_id>"
            )
            flow.python_hook_example = (
                "env['wati.otp.flow'].request_by_key("
                f"'{key}', record, source='python')"
            )
            flow.automation_hook_example = (
                "env['wati.otp.flow'].request_by_key("
                f"'{key}', record, source='automation')"
            )

    def _ensure_integration_secret(self):
        for flow in self:
            if not flow.integration_secret:
                super(
                    WatiOtpFlowUniversalTriggers,
                    flow.with_context(wati_otp_universal_internal=True),
                ).write({"integration_secret": secrets.token_urlsafe(32)})
        return True

    def action_regenerate_integration_secret(self):
        self.ensure_one()
        super(
            WatiOtpFlowUniversalTriggers,
            self.with_context(wati_otp_universal_internal=True),
        ).write({"integration_secret": secrets.token_urlsafe(32)})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Integration secret regenerated"),
                "message": _("Update any external systems that use the old secret."),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def _validate_external_secret(self, provided, entry_point):
        self.ensure_one()
        self._ensure_integration_secret()
        expected = str(self.integration_secret or "")
        supplied = str(provided or "")
        enabled = {
            "api": self.api_enabled,
            "webhook": self.webhook_enabled,
            "website_form": self.website_form_enabled,
        }.get(entry_point, False)
        if not enabled:
            raise UserError(_("This OTP entry point is disabled for the selected flow."))
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            raise UserError(_("Invalid OTP integration secret."))
        return True

    def _sync_universal_server_action(self):
        for flow in self:
            action = flow.universal_server_action_id.sudo().exists()
            if not (flow.active and flow.model_id):
                continue
            vals = {
                "name": f"OTP Bridge Entry · {flow.name}",
                "model_id": flow.model_id.id,
                "state": "code",
                "code": (
                    "if records:\n"
                    f"    flow = env['wati.otp.flow'].sudo().browse({flow.id})\n"
                    "    for record in records:\n"
                    "        flow.request_otp(record, source='server_action')"
                ),
            }
            if action:
                action.write(vals)
            else:
                action = self.env["ir.actions.server"].sudo().create(vals)
                super(
                    WatiOtpFlowUniversalTriggers,
                    flow.with_context(wati_otp_universal_internal=True),
                ).write({"universal_server_action_id": action.id})
        return True

    def _sync_trigger_actions(self):
        result = super()._sync_trigger_actions()
        self._ensure_integration_secret()
        self._sync_universal_server_action()
        return result

    def action_activate(self):
        result = super().action_activate()
        self._ensure_integration_secret()
        self._sync_universal_server_action()
        return result

    def action_prepare_entry_points(self):
        self.ensure_one()
        self._ensure_integration_secret()
        self._sync_universal_server_action()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Universal entry points ready"),
                "message": _("Server action, Python hook, portal, API, webhook, and form entry points are prepared."),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    @api.model
    def request_by_key(self, flow_key, record, source="hook"):
        flow = self.sudo().search(
            [("technical_key", "=", str(flow_key or "").strip()), ("active", "=", True)],
            limit=1,
        )
        if not flow:
            raise UserError(_("No active OTP Flow was found for this integration key."))
        if not record or (flow.model_id and record._name != flow.model_name):
            raise UserError(_("The record does not match this OTP Flow."))
        actual_source = source if source in _ALLOWED_SOURCES else "hook"
        return flow.request_otp(record, source=actual_source)

    @api.model
    def request_by_reference(self, flow_key, res_id, source="api"):
        flow = self.sudo().search(
            [("technical_key", "=", str(flow_key or "").strip()), ("active", "=", True)],
            limit=1,
        )
        if not flow:
            raise UserError(_("No active OTP Flow was found for this integration key."))
        if not flow.model_name or flow.model_name not in self.env:
            raise UserError(_("The OTP Flow record type is unavailable."))
        try:
            record_id = int(res_id or 0)
        except (TypeError, ValueError):
            record_id = 0
        record = self.env[flow.model_name].sudo().browse(record_id).exists()
        if not record:
            raise UserError(_("The source record was not found."))
        actual_source = source if source in _ALLOWED_SOURCES else "api"
        return flow.request_otp(record, source=actual_source)

    def write(self, vals):
        result = super().write(vals)
        watched = {
            "active",
            "model_id",
            "name",
            "api_enabled",
            "webhook_enabled",
            "website_form_enabled",
            "portal_entry_enabled",
        }
        if not self.env.context.get("wati_otp_universal_internal") and set(vals) & watched:
            self._ensure_integration_secret()
            self._sync_universal_server_action()
        return result

    def unlink(self):
        actions = self.mapped("universal_server_action_id").sudo().exists()
        result = super().unlink()
        if actions:
            actions.unlink()
        return result

    def _audit_trigger_snapshot(self, actual_source):
        self.ensure_one()
        labels = {
            "server_action": _("Reusable server action"),
            "automation": _("Automated Action"),
            "api": _("External API · %s") % self.technical_key,
            "webhook": _("Webhook · %s") % self.technical_key,
            "python": _("Python hook · %s") % self.technical_key,
            "website_form": _("Website / form · %s") % self.technical_key,
        }
        if actual_source in labels:
            return labels[actual_source]
        return super()._audit_trigger_snapshot(actual_source)


class WatiOtpTransactionUniversalTriggers(models.Model):
    _inherit = "wati.otp.transaction"

    source = fields.Selection(
        selection_add=[
            ("server_action", "Server action"),
            ("automation", "Automated Action"),
            ("api", "API"),
            ("webhook", "Webhook"),
            ("python", "Python hook"),
            ("website_form", "Website / form"),
        ],
        ondelete={
            "server_action": "set default",
            "automation": "set default",
            "api": "set default",
            "webhook": "set default",
            "python": "set default",
            "website_form": "set default",
        },
    )
