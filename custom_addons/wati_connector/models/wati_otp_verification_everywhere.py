import hmac
import secrets
from datetime import timedelta

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import UserError


_VERIFICATION_SOURCES = {
    "backoffice",
    "portal",
    "pwa",
    "website",
    "api",
}


class WatiOtpFlowVerificationEverywhere(models.Model):
    _inherit = "wati.otp.flow"

    portal_verification_enabled = fields.Boolean(
        string="Portal verification",
        default=True,
        help="Allow signed-in portal/internal users with access to the source record to verify its OTP.",
    )
    pwa_verification_enabled = fields.Boolean(
        string="PWA / Web App verification",
        default=True,
        help="Allow a PWA or browser-based application to verify an OTP using a high-entropy transaction token. No WATI or Odoo integration secret is exposed to the browser.",
    )
    website_verification_enabled = fields.Boolean(
        string="Website verification page",
        default=True,
        help="Provide a standalone responsive OTP verification page that can be opened from a website or embedded workflow.",
    )
    api_verification_enabled = fields.Boolean(
        string="REST API verification",
        default=False,
        help="Allow a trusted backend system to verify, resend, and check OTP status using this flow's integration secret.",
    )

    portal_verify_url_pattern = fields.Char(
        string="Portal verification URL", compute="_compute_verification_urls"
    )
    pwa_verify_url_pattern = fields.Char(
        string="PWA verification API", compute="_compute_verification_urls"
    )
    pwa_status_url_pattern = fields.Char(
        string="PWA status API", compute="_compute_verification_urls"
    )
    website_verify_url_pattern = fields.Char(
        string="Website verification page", compute="_compute_verification_urls"
    )
    api_verify_url = fields.Char(
        string="REST API verification URL", compute="_compute_verification_urls"
    )
    api_resend_url = fields.Char(
        string="REST API resend URL", compute="_compute_verification_urls"
    )
    api_status_url = fields.Char(
        string="REST API status URL", compute="_compute_verification_urls"
    )

    @api.depends("technical_key")
    def _compute_verification_urls(self):
        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url", "") or ""
        ).rstrip("/")
        for flow in self:
            key = flow.technical_key or "FLOW_KEY"
            flow.portal_verify_url_pattern = (
                f"{base_url}/wati/otp/portal/{key}/verify/<record_id>"
            )
            flow.pwa_verify_url_pattern = (
                f"{base_url}/wati/otp/v1/pwa/<verification_token>/verify"
            )
            flow.pwa_status_url_pattern = (
                f"{base_url}/wati/otp/v1/pwa/<verification_token>/status"
            )
            flow.website_verify_url_pattern = (
                f"{base_url}/wati/otp/verify/<verification_token>"
            )
            flow.api_verify_url = f"{base_url}/wati/otp/v1/api/{key}/verify"
            flow.api_resend_url = f"{base_url}/wati/otp/v1/api/{key}/resend"
            flow.api_status_url = f"{base_url}/wati/otp/v1/api/{key}/status"

    def _verification_channel_enabled(self, source):
        self.ensure_one()
        if source == "backoffice":
            return True
        return {
            "portal": self.portal_verification_enabled,
            "pwa": self.pwa_verification_enabled,
            "website": self.website_verification_enabled,
            "api": self.api_verification_enabled,
        }.get(source, False)

    def _validate_verification_secret(self, provided):
        self.ensure_one()
        if not self.api_verification_enabled:
            raise UserError(_("REST API verification is disabled for this OTP Flow."))
        self._ensure_integration_secret()
        expected = str(self.integration_secret or "")
        supplied = str(provided or "")
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            raise UserError(_("Invalid OTP integration secret."))
        return True

    def _latest_transaction_for_record(self, res_id, states=None):
        self.ensure_one()
        if not self.model_name:
            return self.env["wati.otp.transaction"].browse()
        try:
            record_id = int(res_id or 0)
        except (TypeError, ValueError):
            record_id = 0
        domain = [
            ("flow_id", "=", self.id),
            ("model_name", "=", self.model_name),
            ("res_id", "=", record_id),
        ]
        if states:
            domain.append(("state", "in", list(states)))
        return self.env["wati.otp.transaction"].sudo().search(
            domain, order="create_date desc, id desc", limit=1
        )

    def verify_record_code(
        self,
        res_id,
        code,
        source="backoffice",
        verified_by_user_id=None,
        actor=None,
    ):
        self.ensure_one()
        source = source if source in _VERIFICATION_SOURCES else "backoffice"
        if not self._verification_channel_enabled(source):
            raise UserError(_("This verification channel is disabled for the OTP Flow."))
        transaction = self._latest_transaction_for_record(res_id, states=["sent"])
        if not transaction:
            raise UserError(_("There is no OTP waiting for verification on this record."))
        ctx = {
            "wati_verification_source": source,
            "wati_verification_actor": actor or "",
        }
        if verified_by_user_id:
            ctx["wati_verified_by_user_id"] = int(verified_by_user_id)
        ok, message = transaction.with_context(**ctx).verify_code(code)
        return transaction, ok, message


class WatiOtpTransactionVerificationEverywhere(models.Model):
    _inherit = "wati.otp.transaction"

    verification_token = fields.Char(
        string="Verification token",
        default=lambda self: secrets.token_urlsafe(32),
        readonly=True,
        copy=False,
        index=True,
        groups="base.group_system",
    )
    verification_source = fields.Selection(
        [
            ("backoffice", "Odoo Backoffice"),
            ("portal", "Portal"),
            ("pwa", "PWA / Web App"),
            ("website", "Website"),
            ("api", "REST API"),
        ],
        string="Verification channel",
        readonly=True,
        copy=False,
        index=True,
    )
    verification_actor = fields.Char(
        string="Verification actor",
        readonly=True,
        copy=False,
        help="Who or what submitted the latest OTP verification attempt.",
    )
    attempts_remaining = fields.Integer(
        string="Attempts remaining", compute="_compute_attempts_remaining"
    )
    public_verification_url = fields.Char(
        string="Verification page", compute="_compute_public_verification_url"
    )

    @api.depends("attempt_count", "max_attempts")
    def _compute_attempts_remaining(self):
        for transaction in self:
            transaction.attempts_remaining = max(
                0, int(transaction.max_attempts or 0) - int(transaction.attempt_count or 0)
            )

    @api.depends("verification_token", "flow_id.website_verification_enabled")
    def _compute_public_verification_url(self):
        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url", "") or ""
        ).rstrip("/")
        for transaction in self:
            transaction.public_verification_url = (
                f"{base_url}/wati/otp/verify/{transaction.verification_token}"
                if transaction.verification_token
                and transaction.flow_id.website_verification_enabled
                else False
            )

    def _ensure_verification_token(self):
        for transaction in self:
            if not transaction.verification_token:
                transaction.sudo().write(
                    {"verification_token": secrets.token_urlsafe(32)}
                )
        return True

    def verify_code(self, code):
        self.ensure_one()
        source = self.env.context.get("wati_verification_source") or "backoffice"
        source = source if source in _VERIFICATION_SOURCES else "backoffice"
        if not self.flow_id._verification_channel_enabled(source):
            raise UserError(_("This verification channel is disabled for the OTP Flow."))

        actor = self.env.context.get("wati_verification_actor")
        verified_by_user_id = self.env.context.get("wati_verified_by_user_id")
        if not actor:
            user = self.env.user
            actor = (user.display_name or user.name) if user and user.id else source
        self.sudo().write(
            {
                "verification_source": source,
                "verification_actor": str(actor)[:255],
            }
        )

        execution_record = self
        if source in ("pwa", "website", "api") and not verified_by_user_id:
            # Public/external HTTP routes do not have a normal Odoo user. Run the
            # Odoo-side completion workflow as the system user so tracked models,
            # mail.thread hooks, server actions and post-actions always have a valid
            # execution user. The audit channel/actor above still records the real
            # verification surface and we clear the technical verifier below.
            execution_record = self.sudo().with_user(SUPERUSER_ID).with_context(
                self.env.context
            )

        ok, message = super(
            WatiOtpTransactionVerificationEverywhere, execution_record
        ).verify_code(code)
        if ok and source in ("pwa", "website", "api") and not verified_by_user_id:
            # Do not present the system/public user as the human verifier.
            self.sudo().write({"verified_by_id": False})
        return ok, message

    def resend_for_channel(self, source="backoffice", requested_by_user_id=None):
        self.ensure_one()
        source = source if source in _VERIFICATION_SOURCES else "backoffice"
        flow = self.flow_id
        if not flow._verification_channel_enabled(source):
            raise UserError(_("This verification channel is disabled for the OTP Flow."))
        if not flow.allow_resend:
            raise UserError(_("Resend is disabled for this OTP Flow."))
        if self.state == "verified":
            raise UserError(_("This OTP has already been verified."))
        if self.state in ("draft", "cancelled"):
            raise UserError(_("This OTP cannot be resent from its current state."))
        if self.sent_at and flow.resend_cooldown_seconds:
            ready_at = self.sent_at + timedelta(seconds=flow.resend_cooldown_seconds)
            now = fields.Datetime.now()
            if now < ready_at:
                remaining = int((ready_at - now).total_seconds()) + 1
                raise UserError(
                    _("Please wait %s second(s) before resending.") % remaining
                )
        record = self._get_record()
        if not record:
            raise UserError(_("The source record no longer exists."))
        ctx = {}
        if requested_by_user_id:
            ctx["wati_requested_by_user_id"] = int(requested_by_user_id)
        transaction = flow.with_context(**ctx).request_otp(
            record, source="resend", resend_of=self
        )
        transaction._ensure_verification_token()
        return transaction
