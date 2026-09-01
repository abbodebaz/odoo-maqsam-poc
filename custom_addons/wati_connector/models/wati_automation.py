import json
import logging
import re
import time

import requests

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class WatiAutomationRule(models.Model):
    _name = "wati.automation.rule"
    _description = "WATI WhatsApp Automation Rule"
    _order = "sequence, id"

    name = fields.Char(string="اسم القاعدة", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(string="مفعلة", default=True)

    model_id = fields.Many2one(
        "ir.model",
        string="التطبيق / الموديل",
        required=True,
        ondelete="cascade",
        domain=[("transient", "=", False)],
        help="اختر نموذج الأعمال الذي تريد مراقبته مثل CRM أو أوامر البيع أو الفواتير.",
    )
    model_name = fields.Char(related="model_id.model", store=True, readonly=True)
    trigger_field_id = fields.Many2one(
        "ir.model.fields",
        string="الحقل المراقَب",
        required=True,
        domain="[('model_id', '=', model_id), ('store', '=', True)]",
        help="لن تعمل القاعدة إلا عندما يتغير هذا الحقل.",
    )
    condition_operator = fields.Selection(
        [
            ("eq", "يساوي"),
            ("ne", "لا يساوي"),
            ("contains", "يحتوي"),
            ("gt", "أكبر من"),
            ("gte", "أكبر من أو يساوي"),
            ("lt", "أقل من"),
            ("lte", "أقل من أو يساوي"),
            ("is_set", "له قيمة"),
            ("is_not_set", "بدون قيمة"),
        ],
        string="الشرط",
        required=True,
        default="eq",
    )
    target_value = fields.Char(
        string="القيمة المطلوبة",
        help="اكتب القيمة كما تظهر في Odoo. في الحقول المرتبطة يمكن كتابة الاسم أو الرقم الداخلي.",
    )

    recipient_field_id = fields.Many2one(
        "ir.model.fields",
        string="حقل رقم WhatsApp",
        domain="[('model_id', '=', model_id)]",
        help="اختر حقل الهاتف مباشرة إذا كان موجودًا في نفس السجل.",
    )
    recipient_path = fields.Char(
        string="مسار رقم بديل",
        help="اختياري. مثال: partner_id.mobile أو partner_id.phone. إذا تركته فارغًا سيجرب النظام الحقول الشائعة تلقائيًا.",
    )

    template_name = fields.Char(string="اسم WATI Template", required=True)
    channel_number = fields.Char(string="Channel Number", help="اختياري؛ يترك فارغًا لاستخدام الرقم الموجود في إعدادات WATI.")
    once_per_record = fields.Boolean(string="إرسال مرة واحدة لكل سجل", default=True)

    parameter_ids = fields.One2many("wati.automation.parameter", "rule_id", string="متغيرات القالب")
    log_ids = fields.One2many("wati.automation.log", "rule_id", string="سجل التنفيذ")

    base_automation_id = fields.Many2one("base.automation", string="Odoo Automation", readonly=True, copy=False, ondelete="set null")
    server_action_id = fields.Many2one("ir.actions.server", string="Server Action", readonly=True, copy=False, ondelete="set null")

    run_count = fields.Integer(string="عدد التشغيلات", compute="_compute_counts")
    success_count = fields.Integer(string="ناجحة", compute="_compute_counts")
    failure_count = fields.Integer(string="فاشلة", compute="_compute_counts")

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
                raise ValidationError(_("الحقل المراقَب لا ينتمي إلى الموديل المختار."))
            if rule.recipient_field_id and rule.recipient_field_id.model_id != rule.model_id:
                raise ValidationError(_("حقل رقم WhatsApp لا ينتمي إلى الموديل المختار."))

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
                "message": _("تمت مزامنة القاعدة مع محرك Odoo بنجاح."),
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
        digits = re.sub(r"\D+", "", str(value or ""))
        if digits.startswith("00"):
            digits = digits[2:]
        if digits.startswith("0") and len(digits) >= 9:
            digits = "966" + digits[1:]
        elif len(digits) == 9 and digits.startswith("5"):
            digits = "966" + digits
        return digits

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
            return "نعم" if value else "لا"
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
                Log.create(self._log_values(record, "failed", phone="", error_message="لم يتم العثور على رقم WhatsApp في السجل."))
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
        params = self.env["ir.config_parameter"].sudo()
        endpoint = (params.get_param("wati_connector.api_endpoint") or "").strip().rstrip("/")
        token = (params.get_param("wati_connector.api_token") or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        channel = (params.get_param("wati_connector.channel_number") or "").strip()
        return endpoint, token, channel

    def _send_template(self, record, phone, custom_params):
        endpoint, token, configured_channel = self._wati_config()
        Log = self.env["wati.automation.log"].sudo()
        if not endpoint or not token:
            Log.create(self._log_values(record, "failed", phone=phone, error_message="إعدادات WATI API غير مكتملة."))
            return False

        body = {
            "template_name": self.template_name,
            "broadcast_name": f"odoo_auto_{self.id}_{record.id}_{int(time.time())}",
            "receivers": [{"whatsappNumber": phone, "customParams": custom_params}],
        }
        effective_channel = (self.channel_number or configured_channel or "").strip()
        if effective_channel:
            body["channel_number"] = effective_channel

        try:
            response = requests.post(
                f"{endpoint}/api/v1/sendTemplateMessages",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=20,
            )
        except requests.RequestException as exc:
            Log.create(self._log_values(record, "failed", phone=phone, error_message=f"تعذر الاتصال بـ WATI: {exc}"))
            return False

        excerpt = (response.text or response.reason or "").strip()[:1200]
        if not response.ok:
            Log.create(self._log_values(
                record,
                "failed",
                phone=phone,
                error_message=f"WATI رفض الإرسال ({response.status_code}).",
                response_excerpt=excerpt,
            ))
            return False

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
    param_name = fields.Char(string="متغير WATI", required=True)
    source_type = fields.Selection(
        [
            ("field", "حقل من Odoo"),
            ("static", "قيمة ثابتة"),
            ("record_id", "رقم السجل"),
            ("record_name", "اسم السجل"),
        ],
        string="مصدر القيمة",
        default="field",
        required=True,
    )
    source_field_id = fields.Many2one(
        "ir.model.fields",
        string="حقل Odoo",
        domain="[('model_id', '=', model_id)]",
    )
    source_path = fields.Char(string="مسار حقل متقدم", help="اختياري، مثال: partner_id.name")
    static_value = fields.Char(string="قيمة ثابتة")


class WatiAutomationLog(models.Model):
    _name = "wati.automation.log"
    _description = "WATI Automation Execution Log"
    _order = "create_date desc, id desc"

    rule_id = fields.Many2one("wati.automation.rule", required=True, ondelete="cascade", index=True)
    model_name = fields.Char(string="الموديل", index=True)
    res_id = fields.Integer(string="رقم السجل", index=True)
    res_name = fields.Char(string="السجل")
    phone = fields.Char(string="رقم WhatsApp")
    template_name = fields.Char(string="Template")
    status = fields.Selection(
        [("sent", "تم الإرسال"), ("failed", "فشل")],
        string="الحالة",
        required=True,
        index=True,
    )
    error_message = fields.Text(string="الخطأ")
    response_excerpt = fields.Text(string="استجابة WATI")
    triggered_by_id = fields.Many2one("res.users", string="شغّلها", readonly=True)
