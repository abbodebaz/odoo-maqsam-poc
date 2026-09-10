import hashlib
import logging
import re
import time

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.idempotency import WatiIdempotency
from ..utils.phone import normalize_whatsapp_number


_logger = logging.getLogger(__name__)
_TECHNICAL_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_OTP_TOKENS = (
    "otp",
    "verification_code",
    "verify_code",
    "verification",
    "passcode",
    "pin_code",
    "pin",
    "Verification code",
    "Verification code",
    "Symbol",
)
_PHONE_TOKENS = (
    "mobile",
    "whatsapp",
    "wa_id",
    "phone",
    "Mobile",
    "Mobile",
    "WhatsApp",
    "Phone",
)


def _clean(value):
    if value in (None, False):
        return ""
    return str(value).strip()


def _mask_phone(value):
    phone = _clean(value)
    if not phone:
        return ""
    if len(phone) <= 4:
        return "*" * len(phone)
    return ("*" * max(4, len(phone) - 4)) + phone[-4:]


class WatiOtpBridge(models.Model):
    _name = "wati.otp.bridge"
    _description = "WATI OTP Bridge"
    _order = "sequence, id"

    name = fields.Char(string="Link name", required=True)
    technical_key = fields.Char(
        string="Integration key",
        required=True,
        index=True,
        help="A fixed key used by the developer when linking, e.g: driver_login.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(string="Activated", default=False)
    trigger_mode = fields.Selection(
        [
            ("field", "Without programming — When a field changes OTP"),
            ("hook", "Integration Hook — The application passes OTP"),
        ],
        string="Linking method",
        required=True,
        default="field",
    )

    app_menu_id = fields.Many2one(
        "ir.ui.menu",
        string="Application",
        ondelete="set null",
        help="Optional in Integration Hook. Required in the experiment No-Code To facilitate access to the correct model.",
    )
    available_app_menu_ids = fields.Many2many(
        "ir.ui.menu",
        compute="_compute_available_app_menu_ids",
        string="Available applications",
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Model / Record type",
        ondelete="cascade",
        domain=[("transient", "=", False)],
    )
    model_name = fields.Char(related="model_id.model", store=True, readonly=True)
    available_model_ids = fields.Many2many(
        "ir.model",
        compute="_compute_available_model_ids",
        string="Available models",
    )

    otp_field_id = fields.Many2one(
        "ir.model.fields",
        string="Field OTP",
        ondelete="set null",
        domain="[('model_id', '=', model_id), ('store', '=', True), ('ttype', 'in', ['char', 'text', 'integer'])]",
        help="The field that the company application creates and carries a symbol OTP. He doesn’t get up WATI Connector By generating the code.",
    )
    phone_field_id = fields.Many2one(
        "ir.model.fields",
        string="Mobile number field",
        ondelete="set null",
        domain="[('model_id', '=', model_id), ('ttype', 'in', ['char', 'text'])]",
    )
    phone_path = fields.Char(
        string="Mobile number path",
        help="Optional when the number is within a relationship, e.g: partner_id.mobile Or driver_id.mobile.",
    )

    template_id = fields.Many2one(
        "wati.template",
        string="Template OTP In WATI",
        ondelete="restrict",
        domain="[('category', '=', 'AUTHENTICATION'), ('status', '=', 'approved'), ('active', '=', True)]",
        help="It must be a template Authentication Certified and imported from WATI.",
    )
    code_param_name = fields.Char(
        string="variable OTP In the template",
        default="1",
        help="The name of the variable that receives the code within the template. It is automatically suggested from template variables.",
    )
    channel_number = fields.Char(
        string="channel WhatsApp",
        help="Optional. When left blank it uses the Template channel and then the General channel in Settings WATI.",
    )
    dedup_seconds = fields.Integer(
        string="Preventing the same repetition OTP (Again)",
        default=300,
        help="Protects against re-execution Transaction Or write the same code more than once. Does not change validity OTP In the company application.",
    )

    base_automation_id = fields.Many2one(
        "base.automation",
        string="Odoo Automation",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    server_action_id = fields.Many2one(
        "ir.actions.server",
        string="Server Action",
        readonly=True,
        copy=False,
        ondelete="set null",
    )

    log_ids = fields.One2many("wati.otp.log", "bridge_id", string="Register OTP")
    run_count = fields.Integer(string="Attempts", compute="_compute_counts")
    sent_count = fields.Integer(string="Sent", compute="_compute_counts")
    failure_count = fields.Integer(string="Failed", compute="_compute_counts")
    skipped_count = fields.Integer(string="Prevent recurrence", compute="_compute_counts")
    mapping_state = fields.Selection(
        [("incomplete", "Incomplete"), ("ready", "Ready")],
        string="Linkage status",
        compute="_compute_mapping_state",
    )
    mapping_summary = fields.Text(string="Link summary", compute="_compute_mapping_state")

    @api.depends_context("uid")
    def _compute_available_app_menu_ids(self):
        roots = self.env["ir.ui.menu"].get_user_roots()
        for bridge in self:
            bridge.available_app_menu_ids = roots

    @api.depends("app_menu_id")
    def _compute_available_model_ids(self):
        Menu = self.env["ir.ui.menu"]
        IrModel = self.env["ir.model"].sudo()
        Access = self.env["ir.model.access"]
        for bridge in self:
            bridge.available_model_ids = IrModel.browse()
            if not bridge.app_menu_id:
                continue
            menus = Menu.search([("id", "child_of", bridge.app_menu_id.id)])
            try:
                menus = menus._filter_visible_menus()
            except Exception:
                pass
            model_names = set()
            for action in menus.mapped("action"):
                if not action or action._name != "ir.actions.act_window":
                    continue
                model_name = _clean(action.res_model)
                if model_name and model_name in self.env:
                    model_names.add(model_name)
            if not model_names:
                continue
            candidates = IrModel.search(
                [
                    ("model", "in", sorted(model_names)),
                    ("transient", "=", False),
                    ("abstract", "=", False),
                ]
            )
            bridge.available_model_ids = candidates.filtered(
                lambda model: Access.check(model.model, "read", False)
            )

    @api.depends("log_ids", "log_ids.status")
    def _compute_counts(self):
        Log = self.env["wati.otp.log"].sudo()
        for bridge in self:
            domain = [("bridge_id", "=", bridge.id)]
            bridge.run_count = Log.search_count(domain)
            bridge.sent_count = Log.search_count(domain + [("status", "=", "sent")])
            bridge.failure_count = Log.search_count(domain + [("status", "=", "failed")])
            bridge.skipped_count = Log.search_count(domain + [("status", "=", "skipped")])

    @api.depends(
        "active",
        "trigger_mode",
        "model_id",
        "otp_field_id",
        "phone_field_id",
        "phone_path",
        "template_id",
        "template_id.status",
        "template_id.category",
        "code_param_name",
    )
    def _compute_mapping_state(self):
        for bridge in self:
            missing = []
            if bridge.trigger_mode == "field":
                if not bridge.model_id:
                    missing.append("Model")
                if not bridge.otp_field_id:
                    missing.append("Field OTP")
            if bridge.model_id and not bridge.phone_field_id and not _clean(bridge.phone_path):
                missing.append("Mobile number source")
            if not bridge.template_id:
                missing.append("Template Authentication")
            elif bridge.template_id.category != "AUTHENTICATION" or bridge.template_id.status != "approved":
                missing.append("Template Authentication Certified")
            if not _clean(bridge.code_param_name):
                missing.append("variable OTP In the template")

            bridge.mapping_state = "incomplete" if missing else "ready"
            if missing:
                bridge.mapping_summary = "Complete: " + ", ".join(missing)
                continue

            template = bridge.template_id.name
            if bridge.trigger_mode == "field":
                source = bridge.otp_field_id.field_description or bridge.otp_field_id.name
                phone = (
                    bridge.phone_field_id.field_description
                    if bridge.phone_field_id
                    else bridge.phone_path
                )
                bridge.mapping_summary = (
                    f"When it changes «{source}» In {bridge.model_id.name} ← Send «{template}» To {phone}."
                )
            else:
                scope = bridge.model_id.name if bridge.model_id else "Any authorized application"
                bridge.mapping_summary = (
                    f"Integration Hook «{bridge.technical_key}» receives OTP Who {scope} Then send «{template}»."
                )

    @api.onchange("app_menu_id")
    def _onchange_app_menu_id(self):
        for bridge in self:
            bridge.model_id = False
            bridge.otp_field_id = False
            bridge.phone_field_id = False
            bridge.phone_path = False

    @api.onchange("model_id")
    def _onchange_model_id(self):
        for bridge in self:
            if bridge.otp_field_id and bridge.otp_field_id.model_id != bridge.model_id:
                bridge.otp_field_id = False
            if bridge.phone_field_id and bridge.phone_field_id.model_id != bridge.model_id:
                bridge.phone_field_id = False
            bridge.phone_path = False

    @api.onchange("template_id")
    def _onchange_template_id(self):
        for bridge in self:
            if not bridge.template_id:
                continue
            variable = bridge.template_id.variable_ids.sorted("position")[:1]
            if variable and variable.name:
                bridge.code_param_name = variable.name

    @api.constrains("technical_key")
    def _check_technical_key(self):
        for bridge in self:
            key = _clean(bridge.technical_key)
            if not _TECHNICAL_KEY_RE.fullmatch(key):
                raise ValidationError(
                    _("The integral key must start with a lowercase letter and contain only lowercase letters, numbers, and underscores.")
                )
            duplicate = self.search_count(
                [("id", "!=", bridge.id), ("technical_key", "=", key)], limit=1
            )
            if duplicate:
                raise ValidationError(_("The integration key is used in OTP Bridge Another."))

    @api.constrains("model_id", "otp_field_id", "phone_field_id")
    def _check_fields_model(self):
        for bridge in self:
            if bridge.otp_field_id and bridge.otp_field_id.model_id != bridge.model_id:
                raise ValidationError(_("Field OTP It does not belong to the selected model."))
            if bridge.phone_field_id and bridge.phone_field_id.model_id != bridge.model_id:
                raise ValidationError(_("The mobile field does not belong to the selected model."))

    @api.constrains("template_id")
    def _check_auth_template(self):
        for bridge in self:
            if not bridge.template_id:
                continue
            if bridge.template_id.category != "AUTHENTICATION":
                raise ValidationError(_("OTP Bridge Accepts templates Authentication Only."))
            if bridge.template_id.status != "approved":
                raise ValidationError(_("Choose a template Authentication Certified by Meta."))

    @api.constrains("dedup_seconds")
    def _check_dedup_seconds(self):
        for bridge in self:
            if bridge.dedup_seconds < 30 or bridge.dedup_seconds > 3600:
                raise ValidationError(_("The duration of prevention of recurrence should be between 30 And3600 Again."))

    @api.constrains("active", "trigger_mode", "model_id", "otp_field_id", "template_id")
    def _check_active_mapping(self):
        for bridge in self:
            if not bridge.active:
                continue
            if not bridge.template_id or not _clean(bridge.code_param_name):
                raise ValidationError(_("Complete a template OTP And the symbol variable before activation."))
            if bridge.trigger_mode == "field" and (not bridge.model_id or not bridge.otp_field_id):
                raise ValidationError(_("put No-Code Requires a model and field OTP Before activation."))

    @api.model_create_multi
    def create(self, vals_list):
        bridges = super().create(vals_list)
        for bridge in bridges:
            bridge._sync_odoo_automation()
        return bridges

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("wati_otp_internal") and set(vals) & {
            "name",
            "active",
            "trigger_mode",
            "model_id",
            "otp_field_id",
        }:
            for bridge in self:
                bridge._sync_odoo_automation()
        return result

    def unlink(self):
        automations = self.mapped("base_automation_id").sudo().exists()
        result = super().unlink()
        if automations:
            automations.unlink()
        return result

    def _sync_odoo_automation(self):
        self.ensure_one()
        automation = self.base_automation_id.sudo().exists()
        can_run = bool(
            self.active
            and self.trigger_mode == "field"
            and self.model_id
            and self.otp_field_id
        )
        if not can_run:
            if automation and automation.active:
                automation.write({"active": False})
            return

        automation_vals = {
            "name": f"WATI OTP · {self.name}",
            "model_id": self.model_id.id,
            "trigger": "on_create_or_write",
            "trigger_field_ids": [(6, 0, [self.otp_field_id.id])],
            "active": True,
        }
        if automation:
            automation.write(automation_vals)
        else:
            automation = self.env["base.automation"].sudo().create(automation_vals)
            self.with_context(wati_otp_internal=True).write(
                {"base_automation_id": automation.id}
            )

        code = (
            "if record:\n"
            f"    env['wati.otp.bridge'].sudo().browse({self.id})._execute_record(record)"
        )
        action_vals = {
            "name": f"WATI OTP · {self.name}",
            "model_id": self.model_id.id,
            "state": "code",
            "code": code,
            "usage": "base_automation",
            "base_automation_id": automation.id,
        }
        action = self.server_action_id.sudo().exists()
        if action:
            action.write(action_vals)
        else:
            action = self.env["ir.actions.server"].sudo().create(action_vals)
            self.with_context(wati_otp_internal=True).write(
                {"server_action_id": action.id}
            )

    def action_sync(self):
        for bridge in self:
            bridge._sync_odoo_automation()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OTP Bridge"),
                "message": _("The binding is synchronized with the drive Odoo."),
                "type": "success",
                "sticky": False,
            },
        }

    def _field_score(self, field_record, tokens, preferred_names):
        name = _clean(field_record.name).casefold()
        label = _clean(field_record.field_description).casefold()
        if name in preferred_names:
            return 100 - preferred_names.index(name)
        score = 0
        for index, token in enumerate(tokens):
            token = token.casefold()
            if token == name:
                score = max(score, 90 - index)
            elif token in name:
                score = max(score, 70 - index)
            elif token in label:
                score = max(score, 50 - index)
        return score

    def action_auto_detect_fields(self):
        self.ensure_one()
        if not self.model_id:
            raise UserError(_("Choose the application and then the model first."))

        Field = self.env["ir.model.fields"].sudo()
        candidates = Field.search(
            [
                ("model_id", "=", self.model_id.id),
                ("ttype", "in", ["char", "text", "integer"]),
            ]
        )
        otp_candidates = candidates.filtered(lambda field: field.store)
        otp_ranked = sorted(
            otp_candidates,
            key=lambda field: self._field_score(
                field,
                _OTP_TOKENS,
                ["otp", "otp_code", "verification_code", "verify_code", "pin_code"],
            ),
            reverse=True,
        )
        phone_ranked = sorted(
            candidates.filtered(lambda field: field.ttype in ("char", "text")),
            key=lambda field: self._field_score(
                field,
                _PHONE_TOKENS,
                ["mobile", "whatsapp_number", "phone", "wa_id"],
            ),
            reverse=True,
        )

        values = {}
        if otp_ranked and self._field_score(
            otp_ranked[0], _OTP_TOKENS, ["otp", "otp_code", "verification_code", "verify_code", "pin_code"]
        ) > 0:
            values["otp_field_id"] = otp_ranked[0].id

        if phone_ranked and self._field_score(
            phone_ranked[0], _PHONE_TOKENS, ["mobile", "whatsapp_number", "phone", "wa_id"]
        ) > 0:
            values["phone_field_id"] = phone_ranked[0].id
            values["phone_path"] = False
        else:
            partner_field = Field.search(
                [
                    ("model_id", "=", self.model_id.id),
                    ("name", "in", ["partner_id", "contact_id", "customer_id"]),
                    ("ttype", "=", "many2one"),
                    ("relation", "=", "res.partner"),
                ],
                order="id asc",
                limit=1,
            )
            if partner_field:
                values["phone_path"] = f"{partner_field.name}.mobile"
                values["phone_field_id"] = False

        if values:
            self.write(values)
        found = []
        if self.otp_field_id:
            found.append("OTP: " + (self.otp_field_id.field_description or self.otp_field_id.name))
        if self.phone_field_id:
            found.append("Mobile: " + (self.phone_field_id.field_description or self.phone_field_id.name))
        elif self.phone_path:
            found.append("Mobile: " + self.phone_path)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Discover fields"),
                "message": (
                    _("been suggested: %s") % " · ".join(found)
                    if found
                    else _("We did not automatically find clear fields. Choose fields manually or use Integration Hook.")
                ),
                "type": "success" if found else "warning",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def _resolve_path(self, record, path):
        current = record
        for part in [part.strip() for part in _clean(path).split(".") if part.strip()]:
            if not hasattr(current, "_fields") or part not in current._fields:
                return ""
            current = current[part]
            if not current:
                return ""
        if hasattr(current, "_name"):
            if len(current) == 1:
                return current.display_name or ""
            return ""
        return current

    def _record_phone(self, record):
        if self.phone_field_id and self.phone_field_id.name in record._fields:
            value = record[self.phone_field_id.name]
            if value:
                return normalize_whatsapp_number(value)
        if _clean(self.phone_path):
            value = self._resolve_path(record, self.phone_path)
            if value:
                return normalize_whatsapp_number(value)
        for fallback in ("mobile", "phone", "partner_id.mobile", "partner_id.phone"):
            value = self._resolve_path(record, fallback)
            if value:
                return normalize_whatsapp_number(value)
        return ""

    def _record_code(self, record):
        if self.otp_field_id and self.otp_field_id.name in record._fields:
            return _clean(record[self.otp_field_id.name])
        return ""

    def _execute_record(self, record):
        self.ensure_one()
        if (
            not self.active
            or self.trigger_mode != "field"
            or not record
            or record._name != self.model_name
        ):
            return False
        code = self._record_code(record)
        if not code:
            return False
        phone = self._record_phone(record)
        return self._send_otp(record=record, code=code, phone=phone, source="field")

    @api.model
    def send_by_key(self, bridge_key, record=None, code=None, phone=None):
        """Stable integration hook for custom Odoo apps.

        The source application remains responsible for generating, expiring and
        validating OTP. This bridge only delivers the supplied code through an
        approved WATI Authentication template. Provider failures return False so
        the business transaction that generated OTP does not have to fail.
        """
        bridge = self.sudo().search(
            [("technical_key", "=", _clean(bridge_key)), ("active", "=", True)],
            limit=1,
        )
        if not bridge:
            _logger.warning("WATI_OTP_BRIDGE_NOT_FOUND key=%s", _clean(bridge_key))
            return False
        if record and bridge.model_id and record._name != bridge.model_name:
            _logger.warning(
                "WATI_OTP_BRIDGE_MODEL_MISMATCH key=%s expected=%s got=%s",
                bridge.technical_key,
                bridge.model_name,
                record._name,
            )
            return False
        resolved_code = _clean(code) or (bridge._record_code(record) if record else "")
        resolved_phone = normalize_whatsapp_number(phone) if phone else (
            bridge._record_phone(record) if record else ""
        )
        return bridge._send_otp(
            record=record,
            code=resolved_code,
            phone=resolved_phone,
            source="hook",
        )

    def _safe_log_values(
        self,
        *,
        record=None,
        phone="",
        code="",
        source="field",
        status="sent",
        error_message="",
        provider_excerpt="",
    ):
        self.ensure_one()
        fingerprint = hashlib.sha256(_clean(code).encode("utf-8")).hexdigest() if code else ""
        return {
            "bridge_id": self.id,
            "model_name": record._name if record else "",
            "res_id": record.id if record else 0,
            "res_name": (record.display_name or "") if record else "",
            "phone_masked": _mask_phone(phone),
            "template_name": self.template_id.name if self.template_id else "",
            "source": source,
            "status": status,
            "code_fingerprint": fingerprint,
            "error_message": error_message,
            "provider_excerpt": provider_excerpt,
            "triggered_by_id": self.env.user.id,
        }

    def _send_otp(self, *, record=None, code, phone, source="field", force=False):
        self.ensure_one()
        Log = self.env["wati.otp.log"].sudo()
        code = _clean(code)
        phone = normalize_whatsapp_number(phone)

        if not code:
            Log.create(
                self._safe_log_values(
                    record=record,
                    phone=phone,
                    source=source,
                    status="failed",
                    error_message="Symbol OTP empty; No message sent.",
                )
            )
            return False
        if len(code) > 128:
            Log.create(
                self._safe_log_values(
                    record=record,
                    phone=phone,
                    code=code,
                    source=source,
                    status="failed",
                    error_message="Value OTP Longer than the permissible safe limit.",
                )
            )
            return False
        if not phone:
            Log.create(
                self._safe_log_values(
                    record=record,
                    code=code,
                    source=source,
                    status="failed",
                    error_message="No number found WhatsApp Saleh.",
                )
            )
            return False
        if (
            not self.template_id
            or self.template_id.category != "AUTHENTICATION"
            or self.template_id.status != "approved"
        ):
            Log.create(
                self._safe_log_values(
                    record=record,
                    phone=phone,
                    code=code,
                    source=source,
                    status="failed",
                    error_message="Template OTP Not present or not Authentication Certified.",
                )
            )
            return False

        record_model = record._name if record else "manual"
        record_id = record.id if record else 0
        idem = WatiIdempotency(self.env)
        idem_scope = f"wati:otp:{self.id}"
        idem_key = idem.digest(
            self.technical_key,
            record_model,
            record_id,
            phone,
            code,
        )
        if not force and not idem.acquire_durable(
            idem_scope,
            idem_key,
            ttl_seconds=self.dedup_seconds,
        ):
            Log.create(
                self._safe_log_values(
                    record=record,
                    phone=phone,
                    code=code,
                    source=source,
                    status="skipped",
                    error_message="Retransmission of the same has been prevented OTP During the protection window.",
                )
            )
            return False

        client = WatiClient(self.env)
        param_name = _clean(self.code_param_name) or "1"
        body = {
            "template_name": self.template_id.name,
            "broadcast_name": f"odoo_otp_{self.id}_{record_id}_{int(time.time())}",
            "receivers": [
                {
                    "whatsappNumber": phone,
                    "customParams": [{"name": param_name, "value": code}],
                }
            ],
        }
        effective_channel = _clean(
            self.channel_number
            or self.template_id.channel_phone_number
            or client.config.channel_number
        )
        if effective_channel:
            body["channel_number"] = effective_channel

        try:
            response = client.send_template_messages(body)
        except WatiConfigurationError as exc:
            if not force:
                idem.release_durable(idem_scope, idem_key)
            Log.create(
                self._safe_log_values(
                    record=record,
                    phone=phone,
                    code=code,
                    source=source,
                    status="failed",
                    error_message="Settings WATI API Incomplete.",
                )
            )
            _logger.warning("WATI_OTP_CONFIG_ERROR bridge=%s error=%s", self.id, exc)
            return False
        except WatiRequestError as exc:
            detail = _clean(exc.response_text or str(exc))[:1000]
            detail = detail.replace(code, "[OTP REDACTED]") if code else detail
            Log.create(
                self._safe_log_values(
                    record=record,
                    phone=phone,
                    code=code,
                    source=source,
                    status="failed",
                    error_message=(
                        f"WATI Refused to send OTP ({exc.status_code})."
                        if exc.status_code
                        else "Unable to access WATI To send OTP."
                    ),
                    provider_excerpt=detail,
                )
            )
            return False
        except Exception:
            _logger.exception("Unexpected WATI OTP failure bridge=%s", self.id)
            Log.create(
                self._safe_log_values(
                    record=record,
                    phone=phone,
                    code=code,
                    source=source,
                    status="failed",
                    error_message="An unexpected error occurred while sending OTP. Review the server log.",
                )
            )
            return False

        excerpt = _clean(response.text or response.reason)[:1000]
        if code:
            excerpt = excerpt.replace(code, "[OTP REDACTED]")
        Log.create(
            self._safe_log_values(
                record=record,
                phone=phone,
                code=code,
                source=source,
                status="sent",
                provider_excerpt=excerpt,
            )
        )
        return True

    def action_open_test(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Test OTP Bridge"),
            "res_model": "wati.otp.test.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_bridge_id": self.id},
        }

    def action_view_logs(self):
        self.ensure_one()
        action = self.env.ref("wati_connector.action_wati_otp_logs").read()[0]
        action["domain"] = [("bridge_id", "=", self.id)]
        action["context"] = {"default_bridge_id": self.id}
        return action


class WatiOtpLog(models.Model):
    _name = "wati.otp.log"
    _description = "WATI OTP Delivery Log"
    _order = "create_date desc, id desc"

    bridge_id = fields.Many2one("wati.otp.bridge", required=True, ondelete="cascade", index=True)
    model_name = fields.Char(string="Model", index=True)
    res_id = fields.Integer(string="Registration number", index=True)
    res_name = fields.Char(string="Record")
    phone_masked = fields.Char(string="Mobile Number")
    template_name = fields.Char(string="Template WATI")
    source = fields.Selection(
        [("field", "No-Code"), ("hook", "Integration Hook"), ("test", "Manual testing")],
        string="Source",
        required=True,
        default="field",
        index=True,
    )
    status = fields.Selection(
        [("sent", "Sent"), ("failed", "Failed"), ("skipped", "Recurrence prevented")],
        string="Status",
        required=True,
        index=True,
    )
    code_fingerprint = fields.Char(
        string="OTP Fingerprint",
        readonly=True,
        groups="base.group_system",
        help="Imprint SHA-256 Only. The code is not saved OTP Same in a log WATI Connector.",
    )
    error_message = fields.Text(string="Error")
    provider_excerpt = fields.Text(string="response WATI Revised")
    triggered_by_id = fields.Many2one("res.users", string="Play it", readonly=True)


class WatiOtpTestWizard(models.TransientModel):
    _name = "wati.otp.test.wizard"
    _description = "Test WATI OTP Bridge"

    bridge_id = fields.Many2one("wati.otp.bridge", required=True, readonly=True)
    phone = fields.Char(string="No WhatsApp For testing", required=True)
    code = fields.Char(string="OTP Demo", required=True)

    def action_send(self):
        self.ensure_one()
        ok = self.bridge_id._send_otp(
            record=None,
            code=self.code,
            phone=self.phone,
            source="test",
            force=True,
        )
        if not ok:
            raise UserError(_("Test failed OTP. Open a record OTP To find out why."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OTP Bridge"),
                "message": _("has been sent OTP demo via WATI Successfully."),
                "type": "success",
                "sticky": False,
            },
        }
