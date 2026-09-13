import hashlib
import hmac
import logging
import re
import secrets
import time
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..services.idempotency import WatiIdempotency
from ..utils.phone import normalize_whatsapp_number


_logger = logging.getLogger(__name__)
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PHONE_TOKENS = ("mobile", "phone", "whatsapp", "whats_app", "telephone", "tel", "wa_id")
_RELATION_HINTS = ("partner", "customer", "client", "contact", "commercial_partner")
_OTP_NAME_TOKENS = ("otp", "code", "verification", "verify", "pin", "passcode")
_PBKDF2_ITERATIONS = 120000


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


def _slug(value):
    value = re.sub(r"[^a-z0-9]+", "_", _clean(value).lower()).strip("_")
    if not value or not value[0].isalpha():
        value = "otp_flow" if not value else f"otp_{value}"
    return value[:48]


def _generate_code(length=6):
    length = max(4, min(int(length or 6), 8))
    floor = 10 ** (length - 1)
    return str(floor + secrets.randbelow(9 * floor))


def _hash_code(code, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        _clean(code).encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )
    return salt.hex(), digest.hex()


class WatiOtpFlow(models.Model):
    _name = "wati.otp.flow"
    _description = "Managed WATI OTP Flow"
    _order = "sequence, id"

    name = fields.Char(string="Flow name", required=True, index=True)
    technical_key = fields.Char(string="Integration key", required=True, index=True, copy=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=False)
    setup_step = fields.Selection(
        [
            ("source", "1. Source & Trigger"),
            ("recipient", "2. Recipient"),
            ("message", "3. Message"),
            ("verification", "4. Verification"),
        ],
        default="source",
        required=True,
        copy=False,
    )

    # Step 1: source and trigger
    app_menu_id = fields.Many2one("ir.ui.menu", string="Application", ondelete="set null")
    available_app_menu_ids = fields.Many2many(
        "ir.ui.menu", compute="_compute_available_app_menu_ids", string="Available applications"
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Record type",
        ondelete="cascade",
        domain=[("transient", "=", False)],
    )
    model_name = fields.Char(related="model_id.model", store=True, readonly=True)
    available_model_ids = fields.Many2many(
        "ir.model", compute="_compute_available_model_ids", string="Available record types"
    )
    trigger_method = fields.Selection(
        [
            ("manual", "Manual action"),
            ("field", "When a field changes"),
            ("hook", "Integration hook"),
        ],
        default="manual",
        required=True,
        string="Trigger method",
    )
    trigger_field_id = fields.Many2one(
        "ir.model.fields",
        string="Trigger field",
        ondelete="set null",
        domain="[('model_id', '=', model_id), ('store', '=', True)]",
    )
    trigger_operator = fields.Selection(
        [
            ("not_empty", "Has a value"),
            ("equals", "Equals"),
            ("true", "Is true"),
        ],
        default="not_empty",
        string="Trigger condition",
    )
    trigger_value = fields.Char(string="Condition value")

    # Step 2: recipient
    recipient_mode = fields.Selection(
        [
            ("auto", "Automatic — Recommended"),
            ("direct", "Phone from this record"),
            ("related", "Phone from a related record"),
        ],
        default="auto",
        required=True,
        string="Recipient source",
    )
    recipient_path = fields.Char(string="Recipient phone field")
    smart_recipient_metadata = fields.Json(
        string="Smart recipient options", compute="_compute_recipient_state"
    )
    recipient_summary = fields.Char(string="Recipient", compute="_compute_recipient_state")
    recipient_preview_note = fields.Char(
        string="Recipient preview", compute="_compute_recipient_state"
    )

    # Step 3: WATI template and variables
    template_id = fields.Many2one(
        "wati.template",
        string="WATI template",
        ondelete="restrict",
        domain="[('status', '=', 'approved'), ('active', '=', True)]",
    )
    channel_number = fields.Char(
        string="WATI channel number",
        help="Optional. Leave blank to use the template channel or the default WATI channel.",
    )
    binding_ids = fields.One2many(
        "wati.otp.variable.binding", "flow_id", string="Template variables", copy=True
    )

    # Step 4: verification and completion
    code_length = fields.Integer(string="OTP length", default=6)
    validity_minutes = fields.Integer(string="Validity period (minutes)", default=10)
    max_attempts = fields.Integer(string="Maximum attempts", default=5)
    allow_resend = fields.Boolean(string="Allow resend", default=True)
    resend_cooldown_seconds = fields.Integer(string="Resend cooldown (seconds)", default=30)
    completion_mode = fields.Selection(
        [
            ("verified", "Mark OTP as verified only"),
            ("field", "Update a field"),
            ("action", "Run an Odoo server action"),
        ],
        default="verified",
        required=True,
        string="After successful verification",
    )
    completion_field_id = fields.Many2one(
        "ir.model.fields",
        string="Field to update",
        ondelete="set null",
        domain="[('model_id', '=', model_id), ('store', '=', True), ('ttype', 'in', ['char', 'text', 'selection', 'boolean', 'integer', 'float'])]",
    )
    completion_value = fields.Char(string="New value")
    completion_server_action_id = fields.Many2one(
        "ir.actions.server",
        string="Server action",
        ondelete="set null",
        domain="[('model_id', '=', model_id)]",
    )

    # Internal actions
    base_automation_id = fields.Many2one(
        "base.automation", readonly=True, copy=False, ondelete="set null"
    )
    trigger_server_action_id = fields.Many2one(
        "ir.actions.server", readonly=True, copy=False, ondelete="set null"
    )
    manual_action_id = fields.Many2one(
        "ir.actions.server", readonly=True, copy=False, ondelete="set null"
    )

    transaction_ids = fields.One2many("wati.otp.transaction", "flow_id", string="Transactions")
    transaction_count = fields.Integer(compute="_compute_counts")
    waiting_count = fields.Integer(compute="_compute_counts")
    verified_count = fields.Integer(compute="_compute_counts")
    failed_count = fields.Integer(compute="_compute_counts")
    mapping_state = fields.Selection(
        [("incomplete", "Incomplete"), ("ready", "Ready")], compute="_compute_readiness"
    )
    mapping_summary = fields.Char(compute="_compute_readiness")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("technical_key"):
                base = _slug(vals.get("name") or "otp_flow")
                candidate = base
                suffix = 2
                while self.search_count([("technical_key", "=", candidate)], limit=1):
                    candidate = f"{base}_{suffix}"
                    suffix += 1
                vals["technical_key"] = candidate
        flows = super().create(vals_list)
        for flow in flows:
            flow._sync_trigger_actions()
        return flows

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("wati_otp_flow_internal") and set(vals) & {
            "name", "active", "model_id", "trigger_method", "trigger_field_id",
            "trigger_operator", "trigger_value",
        }:
            for flow in self:
                flow._sync_trigger_actions()
        return result

    def unlink(self):
        automations = self.mapped("base_automation_id").sudo().exists()
        actions = (self.mapped("trigger_server_action_id") | self.mapped("manual_action_id")).sudo().exists()
        result = super().unlink()
        if automations:
            automations.unlink()
        if actions:
            actions.unlink()
        return result

    @api.constrains("technical_key")
    def _check_key(self):
        for flow in self:
            key = _clean(flow.technical_key)
            if not _KEY_RE.fullmatch(key):
                raise ValidationError(
                    _("Integration key must start with a lowercase letter and contain only lowercase letters, numbers, and underscores.")
                )
            if self.search_count([("id", "!=", flow.id), ("technical_key", "=", key)], limit=1):
                raise ValidationError(_("This OTP integration key is already in use."))

    @api.constrains("code_length", "validity_minutes", "max_attempts", "resend_cooldown_seconds")
    def _check_security_settings(self):
        for flow in self:
            if flow.code_length < 4 or flow.code_length > 8:
                raise ValidationError(_("OTP length must be between 4 and 8 digits."))
            if flow.validity_minutes < 1 or flow.validity_minutes > 1440:
                raise ValidationError(_("OTP validity must be between 1 minute and 24 hours."))
            if flow.max_attempts < 1 or flow.max_attempts > 20:
                raise ValidationError(_("Maximum OTP attempts must be between 1 and 20."))
            if flow.resend_cooldown_seconds < 0 or flow.resend_cooldown_seconds > 3600:
                raise ValidationError(_("Resend cooldown must be between 0 and 3600 seconds."))

    @api.depends_context("uid")
    def _compute_available_app_menu_ids(self):
        roots = self.env["ir.ui.menu"].get_user_roots()
        for flow in self:
            flow.available_app_menu_ids = roots

    @api.depends("app_menu_id")
    def _compute_available_model_ids(self):
        Menu = self.env["ir.ui.menu"]
        IrModel = self.env["ir.model"].sudo()
        Access = self.env["ir.model.access"]
        for flow in self:
            flow.available_model_ids = IrModel.browse()
            if not flow.app_menu_id:
                continue
            menus = Menu.search([("id", "child_of", flow.app_menu_id.id)])
            try:
                menus = menus._filter_visible_menus()
            except Exception:
                pass
            model_names = set()
            for action in menus.mapped("action"):
                if action and action._name == "ir.actions.act_window" and action.res_model in self.env:
                    model_names.add(action.res_model)
            candidates = IrModel.search([
                ("model", "in", sorted(model_names)),
                ("transient", "=", False),
                ("abstract", "=", False),
            ]) if model_names else IrModel.browse()
            flow.available_model_ids = candidates.filtered(
                lambda model: Access.check(model.model, "read", False)
            )

    @api.onchange("app_menu_id")
    def _onchange_app(self):
        for flow in self:
            flow.model_id = False
            flow.trigger_field_id = False
            flow.recipient_path = False

    @api.onchange("model_id")
    def _onchange_model(self):
        for flow in self:
            flow.trigger_field_id = False
            flow.recipient_path = False
            flow.completion_field_id = False
            flow.completion_server_action_id = False

    def _is_phone_like_field(self, field):
        if getattr(field, "type", "") not in ("char", "text"):
            return False
        haystack = f"{getattr(field, 'name', '')} {getattr(field, 'string', '')}".casefold()
        return any(token in haystack for token in _PHONE_TOKENS)

    def _phone_field_score(self, field):
        name = (getattr(field, "name", "") or "").casefold()
        if name == "mobile":
            return 0
        if name == "phone":
            return 1
        if "whatsapp" in name:
            return 2
        if "mobile" in name:
            return 3
        if "phone" in name:
            return 4
        return 8

    def _relation_score(self, field):
        haystack = f"{getattr(field, 'name', '')} {getattr(field, 'string', '')}".casefold()
        return 0 if any(token in haystack for token in _RELATION_HINTS) else 5

    def _recipient_path_options(self, max_depth=2, limit=80):
        self.ensure_one()
        model_name = self.model_name
        if not model_name or model_name not in self.env:
            return []
        options = []
        seen = set()

        def add(path, label, depth, score):
            if path and path not in seen and len(options) < limit:
                seen.add(path)
                options.append({"value": path, "label": label, "depth": depth, "score": score})

        def walk(current_model, prefix="", label_prefix="", depth=0, visited=None):
            if current_model not in self.env or len(options) >= limit:
                return
            visited = set(visited or set())
            if current_model in visited and depth:
                return
            visited.add(current_model)
            Model = self.env[current_model]
            phone_fields = [f for f in Model._fields.values() if self._is_phone_like_field(f)]
            phone_fields.sort(key=self._phone_field_score)
            for field in phone_fields:
                label = getattr(field, "string", False) or field.name
                path = f"{prefix}.{field.name}" if prefix else field.name
                full_label = f"{label_prefix} → {label}" if label_prefix else label
                add(path, full_label, depth, depth * 20 + self._phone_field_score(field))
            if depth >= max_depth:
                return
            relations = [
                f for f in Model._fields.values()
                if getattr(f, "type", "") == "many2one"
                and getattr(f, "comodel_name", False)
                and f.name not in ("create_uid", "write_uid")
            ]
            relations.sort(key=self._relation_score)
            for field in relations:
                relation = field.comodel_name
                if relation not in self.env:
                    continue
                relation_label = getattr(field, "string", False) or field.name
                next_prefix = f"{prefix}.{field.name}" if prefix else field.name
                next_label = f"{label_prefix} → {relation_label}" if label_prefix else relation_label
                walk(relation, next_prefix, next_label, depth + 1, visited)

        walk(model_name)
        return sorted(options, key=lambda item: (item["score"], item["label"].casefold()))[:limit]

    @api.depends("model_id", "recipient_mode", "recipient_path")
    def _compute_recipient_state(self):
        for flow in self:
            options = flow._recipient_path_options() if flow.model_id else []
            mode = flow.recipient_mode or "auto"
            visible = (
                [item for item in options if item["depth"] == 0]
                if mode == "direct"
                else [item for item in options if item["depth"] > 0]
                if mode == "related"
                else options
            )
            flow.smart_recipient_metadata = {
                "mode": "select" if visible else "empty",
                "placeholder": (
                    "Select a phone field from this record"
                    if mode == "direct"
                    else "Select a phone field from a related record"
                ),
                "options": [
                    {
                        "value": item["value"],
                        "label": item["label"] + (" — Recommended" if index == 0 and len(visible) > 1 else ""),
                    }
                    for index, item in enumerate(visible)
                ],
            }
            selected = next((item for item in options if item["value"] == (flow.recipient_path or "")), None)
            if mode == "auto":
                flow.recipient_summary = _("Automatic")
                flow.recipient_preview_note = _("Odoo will use the best available phone number at send time.")
            elif selected:
                flow.recipient_summary = selected["label"]
                flow.recipient_preview_note = _("WhatsApp will be sent using this phone field.")
            else:
                flow.recipient_summary = _("Choose a phone field")
                flow.recipient_preview_note = _("Select one of the phone fields detected from Odoo.")

    @api.onchange("recipient_mode")
    def _onchange_recipient_mode(self):
        for flow in self:
            flow.recipient_path = False
            options = flow._recipient_path_options() if flow.model_id else []
            mode = flow.recipient_mode or "auto"
            visible = (
                [item for item in options if item["depth"] == 0]
                if mode == "direct"
                else [item for item in options if item["depth"] > 0]
                if mode == "related"
                else options
            )
            if mode != "auto" and len(visible) == 1:
                flow.recipient_path = visible[0]["value"]

    @api.onchange("template_id")
    def _onchange_template(self):
        for flow in self:
            commands = [(5, 0, 0)]
            variables = flow.template_id.variable_ids.sorted("position") if flow.template_id else self.env["wati.template.variable"]
            otp_index = None
            for index, variable in enumerate(variables):
                name = _clean(variable.name).casefold()
                if otp_index is None and any(token in name for token in _OTP_NAME_TOKENS):
                    otp_index = index
            if variables and otp_index is None:
                otp_index = 0
            for index, variable in enumerate(variables):
                commands.append((0, 0, {
                    "sequence": variable.position or index + 1,
                    "variable_name": variable.name,
                    "source_type": "otp" if index == otp_index else "record",
                }))
            flow.binding_ids = commands

    @api.depends(
        "active", "model_id", "trigger_method", "trigger_field_id", "recipient_mode",
        "recipient_path", "template_id", "template_id.status", "binding_ids.source_type",
        "binding_ids.variable_name", "validity_minutes", "max_attempts", "completion_mode",
        "completion_field_id", "completion_server_action_id",
    )
    def _compute_readiness(self):
        for flow in self:
            missing = []
            if not flow.model_id:
                missing.append("record type")
            if flow.trigger_method == "field" and not flow.trigger_field_id:
                missing.append("trigger field")
            if flow.recipient_mode in ("direct", "related") and not _clean(flow.recipient_path):
                missing.append("recipient phone field")
            if not flow.template_id:
                missing.append("WATI template")
            elif flow.template_id.status != "approved":
                missing.append("approved template")
            if flow.template_id and not flow.binding_ids.filtered(lambda line: line.source_type == "otp"):
                missing.append("OTP template variable")
            if flow.completion_mode == "field" and not flow.completion_field_id:
                missing.append("completion field")
            if flow.completion_mode == "action" and not flow.completion_server_action_id:
                missing.append("completion server action")
            flow.mapping_state = "incomplete" if missing else "ready"
            flow.mapping_summary = (
                _("Complete: %s") % ", ".join(missing)
                if missing
                else _("Ready to generate, send, verify, and complete this service flow.")
            )

    def _compute_counts(self):
        Transaction = self.env["wati.otp.transaction"].sudo()
        for flow in self:
            domain = [("flow_id", "=", flow.id)]
            flow.transaction_count = Transaction.search_count(domain)
            flow.waiting_count = Transaction.search_count(domain + [("state", "=", "sent")])
            flow.verified_count = Transaction.search_count(domain + [("state", "=", "verified")])
            flow.failed_count = Transaction.search_count(domain + [("state", "in", ["failed", "expired", "locked"])])

    def _validate_step(self, step=None):
        self.ensure_one()
        step = step or self.setup_step
        if step == "source":
            if not self.model_id:
                raise UserError(_("Choose the application and record type first."))
            if self.trigger_method == "field" and not self.trigger_field_id:
                raise UserError(_("Choose the field that should trigger the OTP."))
        elif step == "recipient":
            if self.recipient_mode in ("direct", "related") and not _clean(self.recipient_path):
                raise UserError(_("Choose which detected phone field should receive the OTP."))
        elif step == "message":
            if not self.template_id or self.template_id.status != "approved":
                raise UserError(_("Choose an approved WATI template."))
            variables = set(self.template_id.variable_ids.mapped("name"))
            mapped = set(self.binding_ids.mapped("variable_name"))
            if variables != mapped:
                raise UserError(_("Template variables changed. Re-select the template to refresh variable mapping."))
            if not self.binding_ids.filtered(lambda line: line.source_type == "otp"):
                raise UserError(_("Map one template variable to OTP Code."))
        elif step == "verification":
            if self.completion_mode == "field" and not self.completion_field_id:
                raise UserError(_("Choose the field to update after successful verification."))
            if self.completion_mode == "action" and not self.completion_server_action_id:
                raise UserError(_("Choose the server action to run after successful verification."))
        return True

    def action_next_step(self):
        self.ensure_one()
        self._validate_step()
        order = ["source", "recipient", "message", "verification"]
        index = order.index(self.setup_step)
        if index < len(order) - 1:
            self.setup_step = order[index + 1]
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def action_previous_step(self):
        self.ensure_one()
        order = ["source", "recipient", "message", "verification"]
        index = order.index(self.setup_step)
        if index > 0:
            self.setup_step = order[index - 1]
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def action_activate(self):
        self.ensure_one()
        for step in ("source", "recipient", "message", "verification"):
            self._validate_step(step)
        self.write({"active": True})
        self._sync_trigger_actions()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OTP Flow activated"),
                "message": _("The service can now generate and verify OTP codes."),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def _sync_trigger_actions(self):
        self.ensure_one()
        automation = self.base_automation_id.sudo().exists()
        automation_action = self.trigger_server_action_id.sudo().exists()
        manual_action = self.manual_action_id.sudo().exists()

        can_field = bool(self.active and self.model_id and self.trigger_method == "field" and self.trigger_field_id)
        if can_field:
            auto_vals = {
                "name": f"WATI OTP Flow · {self.name}",
                "model_id": self.model_id.id,
                "trigger": "on_create_or_write",
                "trigger_field_ids": [(6, 0, [self.trigger_field_id.id])],
                "active": True,
            }
            if automation:
                automation.write(auto_vals)
            else:
                automation = self.env["base.automation"].sudo().create(auto_vals)
                self.with_context(wati_otp_flow_internal=True).write({"base_automation_id": automation.id})
            code = (
                "if record:\n"
                f"    env['wati.otp.flow'].sudo().browse({self.id})._execute_field_trigger(record)"
            )
            action_vals = {
                "name": f"WATI OTP Flow · {self.name}",
                "model_id": self.model_id.id,
                "state": "code",
                "code": code,
                "usage": "base_automation",
                "base_automation_id": automation.id,
            }
            if automation_action:
                automation_action.write(action_vals)
            else:
                automation_action = self.env["ir.actions.server"].sudo().create(action_vals)
                self.with_context(wati_otp_flow_internal=True).write({"trigger_server_action_id": automation_action.id})
        elif automation and automation.active:
            automation.write({"active": False})

        can_manual = bool(self.active and self.model_id and self.trigger_method == "manual")
        if can_manual:
            action_vals = {
                "name": f"Send OTP · {self.name}",
                "model_id": self.model_id.id,
                "binding_model_id": self.model_id.id,
                "binding_type": "action",
                "state": "code",
                "code": (
                    "if records:\n"
                    f"    action = env['wati.otp.flow'].sudo().browse({self.id}).action_request_for_records(records)"
                ),
            }
            if manual_action:
                manual_action.write(action_vals)
            else:
                manual_action = self.env["ir.actions.server"].sudo().create(action_vals)
                self.with_context(wati_otp_flow_internal=True).write({"manual_action_id": manual_action.id})
        elif manual_action and manual_action.binding_model_id:
            manual_action.write({"binding_model_id": False})

    def _match_trigger(self, record):
        self.ensure_one()
        if not self.trigger_field_id or self.trigger_field_id.name not in record._fields:
            return False
        value = record[self.trigger_field_id.name]
        if self.trigger_operator == "true":
            return bool(value)
        if self.trigger_operator == "equals":
            if hasattr(value, "id") and len(value) == 1:
                value = value.id
            return _clean(value).casefold() == _clean(self.trigger_value).casefold()
        return bool(value)

    def _execute_field_trigger(self, record):
        self.ensure_one()
        if not self.active or self.trigger_method != "field" or record._name != self.model_name:
            return False
        if not self._match_trigger(record):
            return False
        return bool(self.request_otp(record, source="field"))

    @api.model
    def request_by_key(self, flow_key, record):
        flow = self.sudo().search([
            ("technical_key", "=", _clean(flow_key)), ("active", "=", True)
        ], limit=1)
        if not flow:
            raise UserError(_("No active OTP Flow was found for this integration key."))
        if not record or (flow.model_id and record._name != flow.model_name):
            raise UserError(_("The record does not match this OTP Flow."))
        return flow.request_otp(record, source="hook")

    def action_request_for_records(self, records):
        self.ensure_one()
        if not records:
            return False
        sent = 0
        for record in records:
            if record._name != self.model_name:
                continue
            if self.request_otp(record, source="manual"):
                sent += 1
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OTP sent"),
                "message": _("Created and sent OTP for %s record(s).") % sent,
                "type": "success" if sent else "warning",
                "sticky": False,
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
            return current.display_name if len(current) == 1 else ""
        return current

    def _record_phone(self, record):
        self.ensure_one()
        options = self._recipient_path_options()
        if self.recipient_mode in ("direct", "related"):
            paths = [self.recipient_path] if self.recipient_path else []
        else:
            paths = [item["value"] for item in options]
        for path in paths:
            value = self._resolve_path(record, path)
            if value:
                phone = normalize_whatsapp_number(value)
                if phone:
                    return phone
        return ""

    def _binding_value(self, binding, record, code):
        if binding.source_type == "otp":
            return code
        if binding.source_type == "static":
            return binding.static_value or ""
        return _clean(self._resolve_path(record, binding.field_path))

    def _build_template_params(self, record, code):
        self.ensure_one()
        params = []
        for binding in self.binding_ids.sorted("sequence"):
            value = self._binding_value(binding, record, code)
            if binding.source_type == "record" and not _clean(binding.field_path):
                raise UserError(_("Choose an Odoo field for template variable %s.") % binding.variable_name)
            params.append({"name": binding.variable_name, "value": _clean(value)})
        return params

    def request_otp(self, record, source="manual", resend_of=None):
        self.ensure_one()
        if not self.active:
            raise UserError(_("Activate this OTP Flow before sending."))
        if not record or record._name != self.model_name:
            raise UserError(_("This record does not match the OTP Flow record type."))
        for step in ("source", "recipient", "message", "verification"):
            self._validate_step(step)
        phone = self._record_phone(record)
        if not phone:
            raise UserError(_("No valid WhatsApp number was found for this record."))

        Transaction = self.env["wati.otp.transaction"].sudo()
        previous = Transaction.search([
            ("flow_id", "=", self.id),
            ("model_name", "=", record._name),
            ("res_id", "=", record.id),
            ("state", "in", ["draft", "sent"]),
        ])
        if previous:
            previous.write({"state": "cancelled", "cancelled_at": fields.Datetime.now()})

        code = _generate_code(self.code_length)
        salt, digest = _hash_code(code)
        now = fields.Datetime.now()
        transaction = Transaction.create({
            "flow_id": self.id,
            "state": "draft",
            "model_name": record._name,
            "res_id": record.id,
            "res_name": record.display_name or "",
            "phone_masked": _mask_phone(phone),
            "code_salt": salt,
            "code_hash": digest,
            "expires_at": now + timedelta(minutes=self.validity_minutes),
            "max_attempts": self.max_attempts,
            "source": source,
            "template_name": self.template_id.name,
            "resend_of_id": resend_of.id if resend_of else False,
            "requested_by_id": self.env.user.id,
        })
        transaction._send_generated_code(code, phone)
        return transaction

    def _coerce_completion_value(self, field_record, value):
        ttype = field_record.ttype
        if ttype == "boolean":
            return _clean(value).casefold() in {"1", "true", "yes", "on"}
        if ttype == "integer":
            return int(value or 0)
        if ttype == "float":
            return float(value or 0.0)
        return value or False

    def _apply_completion(self, transaction):
        self.ensure_one()
        record = transaction._get_record()
        if not record:
            raise UserError(_("The source record no longer exists."))
        if self.completion_mode == "field":
            field = self.completion_field_id
            if not field or field.name not in record._fields:
                raise UserError(_("The completion field is no longer available on this record."))
            record.write({field.name: self._coerce_completion_value(field, self.completion_value)})
        elif self.completion_mode == "action":
            action = self.completion_server_action_id.sudo().exists()
            if not action:
                raise UserError(_("The completion server action is no longer available."))
            action.with_context(
                active_model=record._name,
                active_id=record.id,
                active_ids=record.ids,
            ).run()
        return True

    def action_view_transactions(self):
        self.ensure_one()
        action = self.env.ref("wati_connector.action_wati_otp_transactions").read()[0]
        action["domain"] = [("flow_id", "=", self.id)]
        action["context"] = {"default_flow_id": self.id}
        return action


class WatiOtpVariableBinding(models.Model):
    _name = "wati.otp.variable.binding"
    _description = "OTP Template Variable Binding"
    _order = "sequence, id"

    flow_id = fields.Many2one("wati.otp.flow", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    variable_name = fields.Char(string="Template variable", required=True, readonly=True)
    source_type = fields.Selection(
        [("otp", "OTP Code"), ("record", "Odoo field"), ("static", "Fixed value")],
        default="record",
        required=True,
        string="Value source",
    )
    field_path = fields.Char(string="Odoo field path", help="Example: partner_id.name")
    static_value = fields.Char(string="Fixed value")


class WatiOtpTransaction(models.Model):
    _name = "wati.otp.transaction"
    _description = "Managed OTP Transaction"
    _order = "create_date desc, id desc"

    flow_id = fields.Many2one("wati.otp.flow", required=True, ondelete="cascade", index=True)
    state = fields.Selection(
        [
            ("draft", "Preparing"),
            ("sent", "Waiting Verification"),
            ("verified", "Verified"),
            ("expired", "Expired"),
            ("locked", "Locked"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    model_name = fields.Char(string="Model", required=True, index=True)
    res_id = fields.Integer(string="Record ID", required=True, index=True)
    res_name = fields.Char(string="Record")
    phone_masked = fields.Char(string="WhatsApp number", readonly=True)
    template_name = fields.Char(string="Template", readonly=True)
    source = fields.Selection(
        [("manual", "Manual"), ("field", "Field trigger"), ("hook", "Integration hook"), ("resend", "Resend")],
        default="manual",
        required=True,
        index=True,
    )
    code_salt = fields.Char(readonly=True, groups="base.group_system")
    code_hash = fields.Char(readonly=True, groups="base.group_system")
    expires_at = fields.Datetime(string="Expires at", required=True, index=True)
    attempt_count = fields.Integer(string="Attempts", default=0, readonly=True)
    max_attempts = fields.Integer(string="Maximum attempts", default=5, readonly=True)
    sent_at = fields.Datetime(string="Sent at", readonly=True)
    verified_at = fields.Datetime(string="Verified at", readonly=True)
    verified_by_id = fields.Many2one("res.users", string="Verified by", readonly=True)
    cancelled_at = fields.Datetime(string="Cancelled at", readonly=True)
    requested_by_id = fields.Many2one("res.users", string="Requested by", readonly=True)
    resend_of_id = fields.Many2one("wati.otp.transaction", string="Resend of", readonly=True, ondelete="set null")
    error_message = fields.Text(string="Error", readonly=True)
    provider_excerpt = fields.Text(string="WATI response", readonly=True)

    def _get_record(self):
        self.ensure_one()
        if self.model_name not in self.env:
            return self.env["res.users"].browse()
        return self.env[self.model_name].browse(self.res_id).exists()

    def _is_expired(self):
        self.ensure_one()
        return bool(self.expires_at and fields.Datetime.now() >= self.expires_at)

    def _send_generated_code(self, code, phone):
        self.ensure_one()
        flow = self.flow_id
        client = WatiClient(self.env)
        params = flow._build_template_params(self._get_record(), code)
        body = {
            "template_name": flow.template_id.name,
            "broadcast_name": f"odoo_otpflow_{flow.id}_{self.id}_{int(time.time())}",
            "receivers": [{"whatsappNumber": phone, "customParams": params}],
        }
        effective_channel = _clean(
            flow.channel_number
            or flow.template_id.channel_phone_number
            or client.config.channel_number
        )
        if effective_channel:
            body["channel_number"] = effective_channel

        idem = WatiIdempotency(self.env)
        scope = f"wati:otpflow:{flow.id}"
        key = idem.digest(flow.technical_key, self.id, phone)
        if not idem.acquire_durable(scope, key, ttl_seconds=max(60, flow.validity_minutes * 60)):
            self.write({"state": "failed", "error_message": "Duplicate provider send was prevented."})
            return False
        try:
            response = client.send_template_messages(body)
        except WatiConfigurationError as exc:
            idem.release_durable(scope, key)
            self.write({"state": "failed", "error_message": "WATI API settings are incomplete."})
            _logger.warning("WATI_OTP_FLOW_CONFIG_ERROR flow=%s error=%s", flow.id, exc)
            return False
        except WatiRequestError as exc:
            detail = _clean(exc.response_text or str(exc))[:1000]
            if code:
                detail = detail.replace(code, "[OTP REDACTED]")
            self.write({
                "state": "failed",
                "error_message": (
                    f"WATI rejected the OTP message ({exc.status_code})."
                    if exc.status_code else "Unable to reach WATI while sending OTP."
                ),
                "provider_excerpt": detail,
            })
            return False
        except Exception:
            _logger.exception("Unexpected managed OTP send failure flow=%s transaction=%s", flow.id, self.id)
            self.write({"state": "failed", "error_message": "Unexpected error while sending OTP."})
            return False

        excerpt = _clean(response.text or response.reason)[:1000]
        if code:
            excerpt = excerpt.replace(code, "[OTP REDACTED]")
        self.write({
            "state": "sent",
            "sent_at": fields.Datetime.now(),
            "provider_excerpt": excerpt,
            "error_message": False,
        })
        return True

    def verify_code(self, code):
        self.ensure_one()
        if self.state != "sent":
            return False, _("This OTP is not waiting for verification.")
        if self._is_expired():
            self.write({"state": "expired"})
            return False, _("This OTP has expired. Send a new code.")

        attempts = self.attempt_count + 1
        salt = bytes.fromhex(self.code_salt or "")
        _, digest = _hash_code(code, salt=salt)
        valid = bool(self.code_hash and hmac.compare_digest(digest, self.code_hash))
        if not valid:
            values = {"attempt_count": attempts}
            if attempts >= self.max_attempts:
                values["state"] = "locked"
            self.write(values)
            if values.get("state") == "locked":
                return False, _("Too many incorrect attempts. Send a new OTP.")
            return False, _("Incorrect OTP. %s attempt(s) remaining.") % (self.max_attempts - attempts)

        self.flow_id._apply_completion(self)
        self.write({
            "state": "verified",
            "attempt_count": attempts,
            "verified_at": fields.Datetime.now(),
            "verified_by_id": self.env.user.id,
        })
        return True, _("OTP verified successfully.")

    def action_open_verify(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Verify OTP"),
            "res_model": "wati.otp.verify.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_transaction_id": self.id},
        }

    def action_resend(self):
        self.ensure_one()
        flow = self.flow_id
        if not flow.allow_resend:
            raise UserError(_("Resend is disabled for this OTP Flow."))
        if self.sent_at and flow.resend_cooldown_seconds:
            ready_at = self.sent_at + timedelta(seconds=flow.resend_cooldown_seconds)
            if fields.Datetime.now() < ready_at:
                remaining = int((ready_at - fields.Datetime.now()).total_seconds()) + 1
                raise UserError(_("Please wait %s second(s) before resending.") % remaining)
        record = self._get_record()
        if not record:
            raise UserError(_("The source record no longer exists."))
        return flow.request_otp(record, source="resend", resend_of=self).action_open_verify()

    def action_cancel(self):
        self.filtered(lambda tx: tx.state in ("draft", "sent")).write({
            "state": "cancelled", "cancelled_at": fields.Datetime.now()
        })
        return True

    @api.model
    def _cron_expire_transactions(self):
        expired = self.sudo().search([
            ("state", "=", "sent"), ("expires_at", "<", fields.Datetime.now())
        ], limit=1000)
        if expired:
            expired.write({"state": "expired"})
        return len(expired)


class WatiOtpVerifyWizard(models.TransientModel):
    _name = "wati.otp.verify.wizard"
    _description = "Verify Managed OTP"

    transaction_id = fields.Many2one("wati.otp.transaction", required=True, readonly=True)
    code = fields.Char(string="6-digit OTP", required=True)

    def action_verify(self):
        self.ensure_one()
        code = _clean(self.code)
        if not code.isdigit():
            raise UserError(_("Enter the numeric OTP sent to the customer."))
        ok, message = self.transaction_id.verify_code(code)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("OTP verified") if ok else _("OTP not verified"),
                "message": message,
                "type": "success" if ok else "warning",
                "sticky": not ok,
                "next": {"type": "ir.actions.act_window_close"} if ok else False,
            },
        }
