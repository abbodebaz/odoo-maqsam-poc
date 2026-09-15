import logging
import time

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..services.client import WatiClient
from ..services.config import WatiConfig
from ..services.exceptions import WatiConfigurationError, WatiRequestError
from ..utils.phone import normalize_whatsapp_number

_logger = logging.getLogger(__name__)


class WatiAutomationRule(models.Model):
    _name = "wati.automation.rule"
    _description = "WATI WhatsApp Automation Rule"
    _order = "sequence, id"

    name = fields.Char(string="Rule name", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(string="Activated", default=True)

    model_id = fields.Many2one(
        "ir.model",
        string="Application / Model",
        required=True,
        ondelete="cascade",
        domain=[("transient", "=", False)],
        help="Select the business model you want to monitor e.g CRM Or sales orders or invoices.",
    )
    model_name = fields.Char(related="model_id.model", store=True, readonly=True)
    trigger_field_id = fields.Many2one(
        "ir.model.fields",
        string="Monitored field",
        required=True,
        ondelete="cascade",
        domain="[('model_id', '=', model_id), ('store', '=', True)]",
        help="The rule will only work when this field changes.",
    )
    condition_operator = fields.Selection(
        [
            ("eq", "equals"),
            ("ne", "Not equal"),
            ("contains", "Contains"),
            ("gt", "Greater than"),
            ("gte", "Greater than or equal to"),
            ("lt", "less than"),
            ("lte", "Less than or equal to"),
            ("is_set", "It has value"),
            ("is_not_set", "Without value"),
        ],
        string="Condition",
        required=True,
        default="eq",
    )
    target_value = fields.Char(
        string="Required value",
        help="Type the value as it appears in Odoo. In the associated fields, you can write the name or extension number.",
    )

    recipient_field_id = fields.Many2one(
        "ir.model.fields",
        string="Number field WhatsApp",
        ondelete="set null",
        domain="[('model_id', '=', model_id)]",
        help="Select the Phone field directly if it exists in the same record.",
    )
    recipient_path = fields.Char(
        string="Alternate number path",
        help="Optional. Example: partner_id.mobile Or partner_id.phone. If you leave it blank the system will try common fields automatically.",
    )

    template_name = fields.Char(string="Name WATI Template", required=True)
    channel_number = fields.Char(string="Channel Number", help="Optional; Leave blank to use the number in Settings WATI.")
    once_per_record = fields.Boolean(string="Send once per record", default=True)

    parameter_ids = fields.One2many("wati.automation.parameter", "rule_id", string="Template variables")
    log_ids = fields.One2many("wati.automation.log", "rule_id", string="Execution log")

    base_automation_id = fields.Many2one("base.automation", string="Odoo Automation", readonly=True, copy=False, ondelete="set null")
    server_action_id = fields.Many2one("ir.actions.server", string="Server Action", readonly=True, copy=False, ondelete="set null")

    run_count = fields.Integer(string="Number of runs", compute="_compute_counts")
    success_count = fields.Integer(string="Successful", compute="_compute_counts")
    failure_count = fields.Integer(string="Failed", compute="_compute_counts")

    @api.depends("log_ids", "log_ids.status")
    def _compute_counts(self):
        Log = self.env["wati.automation.log"]
        for rule in self:
            rule.run_count = Log.search_count([("rule_id", "=", rule.id)])
            rule.success_count = Log.search_count([("rule_id", "=", rule.id), ("status", "=", "sent")])
            rule.failure_count = Log.search_count([("rule_id", "=", rule.id), ("status", "=", "failed")])

    @api.constrains("trigger_field_id", "model_id", "recipient_field_id")
    def _check_fields_belong_to_model(self):
        for rule in self:
            if rule.trigger_field_id and rule.trigger_field_id.model_id != rule.model_id:
                raise ValidationError(_("The monitored field does not belong to the selected model."))
            if rule.recipient_field_id and rule.recipient_field_id.model_id != rule.model_id:
                raise ValidationError(_("Number field WhatsApp It does not belong to the selected model."))

    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        for rule in rules:
            rule._sync_odoo_automation()
        return rules

    def write(self, vals):
        result = super().write(vals)
        if set(vals) & {
            "name", "active", "model_id", "trigger_field_id",
        }:
            for rule in self:
                rule._sync_odoo_automation()
        return result

    def unlink(self):
        automations = self.mapped("base_automation_id")
        result = super().unlink()
        automations.sudo().unlink()
        return result

    def action_sync(self):
        for rule in self:
            rule._sync_odoo_automation()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WhatsApp Automation"),
                "message": _("The base is synchronized with the drive Odoo Successfully."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_view_logs(self):
        self.ensure_one()
        action = self.env.ref("wati_connector.action_wati_automation_logs").read()[0]
        action["domain"] = [("rule_id", "=", self.id)]
        action["context"] = {"default_rule_id": self.id}
        return action

    def _sync_odoo_automation(self):
        self.ensure_one()
        if not self.id or not self.model_id or not self.trigger_field_id:
            return

        automation_vals = {
            "name": f"WATI · {self.name}",
            "model_id": self.model_id.id,
            "trigger": "on_create_or_write",
            "trigger_field_ids": [(6, 0, [self.trigger_field_id.id])],
            "active": bool(self.active),
        }

        automation = self.base_automation_id.sudo().exists()
        if automation:
            automation.write(automation_vals)
        else:
            automation = self.env["base.automation"].sudo().create(automation_vals)
            super(WatiAutomationRule, self).write({"base_automation_id": automation.id})

        code = (
            "if record:\n"
            f"    env['wati.automation.rule'].sudo().browse({self.id})._execute_record(record)"
        )
        action_vals = {
            "name": f"WATI · {self.name}",
            "model_id": self.model_id.id,
            "state": "code",
            "code": code,
            "usage": "base_automation",
            "base_automation_id": automation.id,
        }
        server_action = self.server_action_id.sudo().exists()
        if server_action:
            server_action.write(action_vals)
        else:
            server_action = self.env["ir.actions.server"].sudo().create(action_vals)
            super(WatiAutomationRule, self).write({"server_action_id": server_action.id})

    def _selection_label(self, record, field_name, raw_value):
        try:
            field = record._fields[field_name]
            selection = field._description_selection(record.env)
            return dict(selection).get(raw_value, "")
        except Exception:
            return ""

    def _value_candidates(self, record, field_name):
        value = record[field_name]
        field = record._fields[field_name]
        candidates = []
        if field.type == "many2one":
            if value:
                candidates.extend([str(value.id), value.display_name or ""])
                if "name" in value._fields and value.name:
                    candidates.append(str(value.name))
                if "code" in value._fields and value.code:
                    candidates.append(str(value.code))
        elif field.type in ("many2many", "one2many"):
            candidates.extend([str(item.id) for item in value])
            candidates.extend([item.display_name or "" for item in value])
        else:
            candidates.append("" if value is False or value is None else str(value))
            if field.type == "selection":
                label = self._selection_label(record, field_name, value)
                if label:
                    candidates.append(str(label))
        return [str(item).strip() for item in candidates if str(item).strip()]

    def _condition_matches(self, record):
        self.ensure_one()
        field_name = self.trigger_field_id.name
        if field_name not in record._fields:
            return False
        raw = record[field_name]
        op = self.condition_operator
        if op == "is_set":
            return bool(raw)
        if op == "is_not_set":
            return not bool(raw)

        target = str(self.target_value or "").strip()
        candidates = self._value_candidates(record, field_name)
        if op == "eq":
            return any(item.casefold() == target.casefold() for item in candidates)
        if op == "ne":
            return all(item.casefold() != target.casefold() for item in candidates)
        if op == "contains":
            return any(target.casefold() in item.casefold() for item in candidates)

        try:
            actual = float(candidates[0]) if candidates else 0.0
            wanted = float(target)
        except (TypeError, ValueError):
            return False
        if op == "gt":
            return actual > wanted
        if op == "gte":
            return actual >= wanted
        if op == "lt":
            return actual < wanted
        if op == "lte":
            return actual <= wanted
        return False

    def _resolve_path(self, record, path):
        current = record
        for part in [p.strip() for p in str(path or "").split(".") if p.strip()]:
            if not hasattr(current, "_fields") or part not in current._fields:
                return ""
            current = current[part]
            if not current:
                return ""
        if hasattr(current, "_name"):
            if len(current) == 1:
                return current.display_name or ""
            return ", ".join(current.mapped("display_name"))
        return current

    def _recipient_phone(self, record):
        path = (self.recipient_path or "").strip()
        if path:
            value = self._resolve_path(record, path)
            if value:
                return self._normalize_phone(value)
        if self.recipient_field_id and self.recipient_field_id.name in record._fields:
            value = record[self.recipient_field_id.name]
            if value:
                return self._normalize_phone(value)
        for fallback in ("mobile", "phone", "partner_id.mobile", "partner_id.phone"):
            value = self._resolve_path(record, fallback)
            if value:
                return self._normalize_phone(value)
        return ""

    @api.model
    def _normalize_phone(self, value):
        return normalize_whatsapp_number(value)

    def _parameter_value(self, record, line):
        if line.source_type == "static":
            return line.static_value or ""
        if line.source_type == "record_id":
            return str(record.id)
        if line.source_type == "record_name":
            return record.display_name or ""
        path = (line.source_path or "").strip()
        if not path and line.source_field_id:
            path = line.source_field_id.name
        value = self._resolve_path(record, path)
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if value is None or value is False:
            return ""
        return str(value)

    def _execute_record(self, record):
        self.ensure_one()
        if not self.active or not record or record._name != self.model_name:
            return False
        try:
            if not self._condition_matches(record):
                return False

            Log = self.env["wati.automation.log"].sudo()
            if self.once_per_record and Log.search_count([
                ("rule_id", "=", self.id),
                ("model_name", "=", record._name),
                ("res_id", "=", record.id),
                ("status", "=", "sent"),
            ], limit=1):
                return False

            phone = self._recipient_phone(record)
            if not phone:
                Log.create(self._log_values(record, "failed", phone="", error_message="No number found WhatsApp In the register."))
                return False

            custom_params = [
                {"name": line.param_name, "value": self._parameter_value(record, line)}
                for line in self.parameter_ids.sorted("sequence")
                if line.param_name
            ]
            return self._send_template(record, phone, custom_params)
        except Exception as exc:
            _logger.exception("WATI automation rule %s failed", self.id)
            try:
                self.env["wati.automation.log"].sudo().create(
                    self._log_values(record, "failed", error_message=str(exc)[:1000])
                )
            except Exception:
                _logger.exception("Could not write WATI automation failure log")
            return False

    def _wati_config(self):
        config = WatiConfig(self.env)
        return config.endpoint, config.token, config.channel_number

    def _send_template(self, record, phone, custom_params):
        Log = self.env["wati.automation.log"].sudo()
        client = WatiClient(self.env)
        configured_channel = client.config.channel_number

        body = {
            "template_name": self.template_name,
            "broadcast_name": f"odoo_auto_{self.id}_{record.id}_{int(time.time())}",
            "receivers": [{"whatsappNumber": phone, "customParams": custom_params}],
        }
        effective_channel = (self.channel_number or configured_channel or "").strip()
        if effective_channel:
            body["channel_number"] = effective_channel

        try:
            response = client.send_template_messages(body)
        except WatiConfigurationError:
            Log.create(self._log_values(
                record,
                "failed",
                phone=phone,
                error_message="Settings WATI API Incomplete.",
            ))
            return False
        except WatiRequestError as exc:
            detail = (exc.response_text or str(exc) or "").strip()[:1200]
            Log.create(self._log_values(
                record,
                "failed",
                phone=phone,
                error_message=(
                    f"WATI Refused to send ({exc.status_code})."
                    if exc.status_code
                    else f"Unable to contact WATI: {detail}"
                ),
                response_excerpt=detail,
            ))
            return False

        excerpt = (response.text or response.reason or "").strip()[:1200]
        Log.create(self._log_values(record, "sent", phone=phone, response_excerpt=excerpt))
        return True

    def _log_values(self, record, status, phone="", error_message="", response_excerpt=""):
        return {
            "rule_id": self.id,
            "model_name": record._name,
            "res_id": record.id,
            "res_name": record.display_name or "",
            "phone": phone,
            "template_name": self.template_name,
            "status": status,
            "error_message": error_message,
            "response_excerpt": response_excerpt,
            "triggered_by_id": self.env.user.id,
        }


class WatiAutomationParameter(models.Model):
    _name = "wati.automation.parameter"
    _description = "WATI Automation Template Parameter"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    rule_id = fields.Many2one("wati.automation.rule", required=True, ondelete="cascade")
    model_id = fields.Many2one(related="rule_id.model_id", store=True, readonly=True)
    param_name = fields.Char(string="variable WATI", required=True)
    source_type = fields.Selection(
        [
            ("field", "field of Odoo"),
            ("static", "Fixed value"),
            ("record_id", "Registration number"),
            ("record_name", "Record name"),
        ],
        string="Source of value",
        default="field",
        required=True,
    )
    source_field_id = fields.Many2one(
        "ir.model.fields",
        string="Field Odoo",
        ondelete="set null",
        domain="[('model_id', '=', model_id)]",
    )
    source_path = fields.Char(string="Advanced field path", help="Optional, example: partner_id.name")
    static_value = fields.Char(string="Fixed value")


class WatiAutomationLog(models.Model):
    _name = "wati.automation.log"
    _description = "WATI Automation Execution Log"
    _order = "create_date desc, id desc"

    rule_id = fields.Many2one("wati.automation.rule", required=True, ondelete="cascade", index=True)
    model_name = fields.Char(string="Model", index=True)
    res_id = fields.Integer(string="Registration number", index=True)
    res_name = fields.Char(string="Record")
    phone = fields.Char(string="No WhatsApp")
    template_name = fields.Char(string="Template")
    status = fields.Selection(
        [("sent", "Sent"), ("failed", "Failed")],
        string="Status",
        required=True,
        index=True,
    )
    error_message = fields.Text(string="Error")
    response_excerpt = fields.Text(string="response WATI")
    triggered_by_id = fields.Many2one("res.users", string="Play it", readonly=True)
