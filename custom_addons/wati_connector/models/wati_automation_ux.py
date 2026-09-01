import re

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .wati_automation_improvements import (
    _find_template_list,
    _template_body,
    _template_name,
    _template_param_names,
)


_OPERATOR_LABELS = {
    "eq": "يساوي",
    "ne": "لا يساوي",
    "contains": "يحتوي",
    "gt": "أكبر من",
    "gte": "أكبر من أو يساوي",
    "lt": "أقل من",
    "lte": "أقل من أو يساوي",
    "is_set": "له قيمة",
    "is_not_set": "بدون قيمة",
}

_GENERAL_TEMPLATE_NAMES = {"whatsapp", "wati", "unknown", "none", "null"}


class WatiAutomationRuleUX(models.Model):
    _inherit = "wati.automation.rule"

    # New rules should be reviewed before activation. Existing rules keep their DB value.
    active = fields.Boolean(default=False)
    template_name = fields.Char(string="WATI Template", required=False)

    setup_step = fields.Selection(
        [
            ("trigger", "1. متى؟"),
            ("recipient", "2. لمن؟"),
            ("message", "3. الرسالة"),
            ("review", "4. مراجعة"),
        ],
        string="خطوة الإعداد",
        default="trigger",
        required=True,
        copy=False,
    )
    preset_key = fields.Selection(
        [
            ("crm_qualified", "CRM · عند التأهيل Qualified"),
            ("crm_won", "CRM · عند الفوز Won"),
            ("sale_confirmed", "المبيعات · عند تأكيد الطلب"),
            ("invoice_posted", "الفواتير · عند الترحيل"),
            ("invoice_paid", "الفواتير · عند السداد"),
        ],
        string="ابدأ من إعداد جاهز",
        copy=False,
    )
    human_summary = fields.Char(string="ملخص القاعدة", compute="_compute_ux_state")
    readiness_state = fields.Selection(
        [("ready", "جاهزة"), ("warning", "تحتاج مراجعة"), ("incomplete", "غير مكتملة")],
        string="الجاهزية",
        compute="_compute_ux_state",
    )
    readiness_message = fields.Text(string="فحص الجاهزية", compute="_compute_ux_state")
    template_body = fields.Text(string="نص القالب", readonly=True, copy=False)
    preview_text = fields.Text(string="معاينة الرسالة", readonly=True, copy=False)
    preview_record_name = fields.Char(string="سجل المعاينة", readonly=True, copy=False)
    test_phone = fields.Char(string="رقم اختبار", copy=False, help="لن يتم استخدام رقم العميل عند الإرسال التجريبي.")

    @api.depends(
        "name", "model_id", "trigger_field_id", "condition_operator", "target_value",
        "recipient_field_id", "recipient_path", "template_name", "once_per_record",
        "parameter_ids.param_name", "parameter_ids.source_type", "parameter_ids.source_field_id",
        "parameter_ids.source_path", "parameter_ids.static_value",
    )
    def _compute_ux_state(self):
        params = self.env["ir.config_parameter"].sudo()
        api_ready = bool(
            (params.get_param("wati_connector.api_endpoint") or "").strip()
            and (params.get_param("wati_connector.api_token") or "").strip()
        )
        for rule in self:
            model_label = rule.model_id.name or "التطبيق"
            field_label = rule.trigger_field_id.field_description or rule.trigger_field_id.name or "الحقل"
            operator = _OPERATOR_LABELS.get(rule.condition_operator, rule.condition_operator or "")
            target = (rule.target_value or "").strip()
            if rule.condition_operator in ("is_set", "is_not_set"):
                condition_text = f"{field_label} {operator}"
            elif target:
                condition_text = f"{field_label} {operator} «{target}»"
            else:
                condition_text = f"{field_label} {operator} ..."

            if rule.recipient_field_id:
                recipient = rule.recipient_field_id.field_description or rule.recipient_field_id.name
            elif rule.recipient_path:
                recipient = rule.recipient_path
            else:
                recipient = "رقم العميل تلقائيًا"

            template = rule.template_name or "قالب لم يُحدد بعد"
            once = " · مرة واحدة لكل سجل" if rule.once_per_record else ""
            rule.human_summary = (
                f"عندما {condition_text} في {model_label} ← أرسل «{template}» إلى {recipient}{once}"
            )

            errors = []
            warnings = []
            if not rule.name:
                errors.append("اسم القاعدة")
            if not rule.model_id:
                errors.append("التطبيق / الموديل")
            if not rule.trigger_field_id:
                errors.append("الحقل المراقَب")
            if rule.condition_operator not in ("is_set", "is_not_set") and not target:
                errors.append("القيمة المطلوبة")
            if not rule.template_name:
                errors.append("قالب WATI")
            if not api_ready:
                errors.append("اتصال WATI API")

            unmapped = []
            for line in rule.parameter_ids:
                if not line.param_name:
                    continue
                mapped = (
                    line.source_type in ("record_id", "record_name")
                    or (line.source_type == "static" and bool((line.static_value or "").strip()))
                    or (
                        line.source_type == "field"
                        and bool(line.source_field_id or (line.source_path or "").strip())
                    )
                )
                if not mapped:
                    unmapped.append(line.param_name)
            if unmapped:
                errors.append("متغيرات غير مربوطة: " + ", ".join(unmapped[:6]))
            if rule.template_name and not rule.parameter_ids:
                warnings.append("لم يتم جلب متغيرات القالب بعد؛ إذا كان القالب يحتوي متغيرات اضغط جلب المتغيرات.")
            if not rule.recipient_field_id and not rule.recipient_path:
                warnings.append("سيبحث النظام تلقائيًا عن mobile / phone / رقم العميل المرتبط.")

            if errors:
                rule.readiness_state = "incomplete"
            elif warnings:
                rule.readiness_state = "warning"
            else:
                rule.readiness_state = "ready"

            checklist = []
            checklist.append("✅ التطبيق والحدث محددان" if rule.model_id and rule.trigger_field_id else "❌ حدد التطبيق والحقل المراقَب")
            checklist.append("✅ الشرط مكتمل" if (rule.condition_operator in ("is_set", "is_not_set") or target) else "❌ حدد القيمة المطلوبة")
            checklist.append("✅ قالب WATI محدد" if rule.template_name else "❌ اختر قالب WATI")
            checklist.append("✅ اتصال WATI جاهز" if api_ready else "❌ إعدادات WATI API غير مكتملة")
            if unmapped:
                checklist.append("❌ اربط: " + ", ".join(unmapped[:6]))
            elif rule.parameter_ids:
                checklist.append(f"✅ {len(rule.parameter_ids)} متغيرات مربوطة")
            elif rule.template_name:
                checklist.append("⚠️ لا توجد متغيرات محملة للقالب")
            if warnings:
                checklist.extend("⚠️ " + item for item in warnings)
            rule.readiness_message = "\n".join(checklist)

    def _validate_step(self, step=None):
        self.ensure_one()
        step = step or self.setup_step
        if step == "trigger":
            missing = []
            if not self.name:
                missing.append("اسم القاعدة")
            if not self.model_id:
                missing.append("التطبيق")
            if not self.trigger_field_id:
                missing.append("الحقل المراقَب")
            if self.condition_operator not in ("is_set", "is_not_set") and not (self.target_value or "").strip():
                missing.append("القيمة المطلوبة")
            if missing:
                raise UserError(_("أكمل الخطوة الأولى: %s", "، ".join(missing)))
        elif step == "message":
            if not self.template_name:
                raise UserError(_("اختر قالب WATI أولًا."))

    def _validate_activation(self):
        self.ensure_one()
        self._compute_ux_state()
        if self.readiness_state == "incomplete":
            raise ValidationError(_("القاعدة غير جاهزة للتفعيل:\n%s", self.readiness_message))

    def action_next_step(self):
        self.ensure_one()
        self._validate_step(self.setup_step)
        order = ["trigger", "recipient", "message", "review"]
        idx = order.index(self.setup_step)
        if idx < len(order) - 1:
            self.setup_step = order[idx + 1]
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def action_previous_step(self):
        self.ensure_one()
        order = ["trigger", "recipient", "message", "review"]
        idx = order.index(self.setup_step)
        if idx > 0:
            self.setup_step = order[idx - 1]
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def action_activate_rule(self):
        self.ensure_one()
        self._validate_activation()
        self.write({"active": True, "setup_step": "review"})
        self._sync_odoo_automation()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("تم تفعيل الأتمتة"),
                "message": self.human_summary,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def action_deactivate_rule(self):
        self.ensure_one()
        self.write({"active": False})
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def write(self, vals):
        result = super().write(vals)
        if vals.get("active") is True:
            for rule in self:
                rule._validate_activation()
        return result

    def action_duplicate_rule(self):
        self.ensure_one()
        duplicate = self.copy(default={
            "name": _("%s — نسخة", self.name),
            "active": False,
            "setup_step": "trigger",
            "base_automation_id": False,
            "server_action_id": False,
            "preview_text": False,
            "preview_record_name": False,
            "test_phone": False,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("نسخة من القاعدة"),
            "res_model": "wati.automation.rule",
            "res_id": duplicate.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_apply_preset(self):
        self.ensure_one()
        presets = {
            "crm_qualified": ("crm.lead", "stage_id", "Qualified", ("mobile", "phone"), "CRM · إرسال عند Qualified"),
            "crm_won": ("crm.lead", "stage_id", "Won", ("mobile", "phone"), "CRM · إرسال عند Won"),
            "sale_confirmed": ("sale.order", "state", "sale", (), "المبيعات · إرسال عند تأكيد الطلب"),
            "invoice_posted": ("account.move", "state", "posted", (), "الفواتير · إرسال عند الترحيل"),
            "invoice_paid": ("account.move", "payment_state", "paid", (), "الفواتير · إرسال عند السداد"),
        }
        preset = presets.get(self.preset_key)
        if not preset:
            raise UserError(_("اختر إعدادًا جاهزًا أولًا."))
        model_name, field_name, target, recipient_fields, default_name = preset
        model = self.env["ir.model"].sudo().search([("model", "=", model_name)], limit=1)
        if not model:
            raise UserError(_("التطبيق المطلوب غير مثبت حاليًا في Odoo: %s", model_name))
        trigger = self.env["ir.model.fields"].sudo().search([
            ("model_id", "=", model.id), ("name", "=", field_name)
        ], limit=1)
        if not trigger:
            raise UserError(_("لم أجد الحقل %s في التطبيق المختار.", field_name))
        recipient = False
        for rec_name in recipient_fields:
            recipient = self.env["ir.model.fields"].sudo().search([
                ("model_id", "=", model.id), ("name", "=", rec_name)
            ], limit=1)
            if recipient:
                break
        vals = {
            "name": self.name or default_name,
            "model_id": model.id,
            "trigger_field_id": trigger.id,
            "condition_operator": "eq",
            "target_value": target,
            "recipient_field_id": recipient.id if recipient else False,
            "recipient_path": False if recipient else "partner_id.mobile",
            "once_per_record": True,
            "setup_step": "trigger",
        }
        self.write(vals)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("تم تطبيق الإعداد الجاهز"),
                "message": self.human_summary,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def _target_choices(self):
        self.ensure_one()
        if not self.model_id or not self.trigger_field_id:
            return []
        Model = self.env.get(self.model_name)
        if not Model or self.trigger_field_id.name not in Model._fields:
            return []
        field = Model._fields[self.trigger_field_id.name]
        if field.type == "selection":
            try:
                return [(str(value), str(label)) for value, label in field._description_selection(self.env)]
            except Exception:
                return []
        if field.type == "many2one":
            try:
                records = self.env[field.comodel_name].sudo().search([], limit=150)
                return [(str(record.id), record.display_name or str(record.id)) for record in records]
            except Exception:
                return []
        if field.type == "boolean":
            return [("True", _("نعم")), ("False", _("لا"))]
        return []

    def action_pick_target_value(self):
        self.ensure_one()
        choices = self._target_choices()
        if not choices:
            raise UserError(_("هذا الحقل لا يحتوي قائمة قيم جاهزة؛ اكتب القيمة المطلوبة يدويًا."))
        Choice = self.env["wati.automation.value.choice"]
        Choice.search([("rule_id", "=", self.id)]).unlink()
        Choice.create([
            {"rule_id": self.id, "value": value, "label": label}
            for value, label in choices
        ])
        return {
            "type": "ir.actions.act_window",
            "name": _("اختر القيمة المطلوبة"),
            "res_model": "wati.automation.value.choice",
            "view_mode": "list",
            "views": [(self.env.ref("wati_connector.view_wati_automation_value_choice_list").id, "list")],
            "domain": [("rule_id", "=", self.id)],
            "target": "new",
        }

    def _fetch_wati_templates(self):
        self.ensure_one()
        endpoint, token, _channel = self._wati_config()
        if not endpoint or not token:
            raise UserError(_("إعدادات WATI API غير مكتملة."))
        try:
            response = requests.get(
                f"{endpoint}/api/v1/getMessageTemplates",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                params={"pageSize": 200, "pageNumber": 1},
                timeout=25,
            )
        except requests.RequestException as exc:
            raise UserError(_("تعذر الاتصال بـ WATI: %s", exc)) from exc
        if not response.ok:
            detail = (response.text or response.reason or "").strip()[:700]
            raise UserError(_("WATI رفض جلب القوالب (%(status)s): %(detail)s", status=response.status_code, detail=detail))
        try:
            return _find_template_list(response.json())
        except ValueError as exc:
            raise UserError(_("WATI أعاد استجابة غير مفهومة عند جلب القوالب.")) from exc

    def action_pick_template(self):
        self.ensure_one()
        templates = self._fetch_wati_templates()
        if not templates:
            raise UserError(_("لم أجد قوالب WhatsApp في حساب WATI."))
        Choice = self.env["wati.automation.template.choice"]
        Choice.search([("rule_id", "=", self.id)]).unlink()
        vals_list = []
        for item in templates:
            name = _template_name(item)
            if not name or name.casefold() in _GENERAL_TEMPLATE_NAMES:
                continue
            status = str(item.get("status") or item.get("approvalStatus") or item.get("templateStatus") or "") if isinstance(item, dict) else ""
            category = str(item.get("category") or item.get("type") or "") if isinstance(item, dict) else ""
            vals_list.append({
                "rule_id": self.id,
                "name": name,
                "status": status,
                "category": category,
                "body": _template_body(item),
            })
        if vals_list:
            Choice.create(vals_list)
        return {
            "type": "ir.actions.act_window",
            "name": _("اختر قالب WATI"),
            "res_model": "wati.automation.template.choice",
            "view_mode": "list",
            "views": [(self.env.ref("wati_connector.view_wati_automation_template_choice_list").id, "list")],
            "domain": [("rule_id", "=", self.id)],
            "target": "new",
        }

    def _auto_map_parameters(self):
        self.ensure_one()
        if not self.model_id:
            return 0
        Fields = self.env["ir.model.fields"].sudo()
        model_fields = Fields.search([("model_id", "=", self.model_id.id)])
        by_name = {field.name.casefold(): field for field in model_fields}
        mapped = 0
        for line in self.parameter_ids:
            if line.source_type != "field" or line.source_field_id or (line.source_path or "").strip():
                continue
            key = re.sub(r"[^a-z0-9]+", "_", (line.param_name or "").casefold()).strip("_")
            target_field = by_name.get(key)
            vals = {}
            if target_field:
                vals["source_field_id"] = target_field.id
            elif any(token in key for token in ("client", "customer", "contact")) and "partner_id" in by_name:
                vals["source_path"] = "partner_id.name"
            elif key in ("id", "record_id") or key.endswith("_id2") or key.endswith("_id"):
                vals["source_type"] = "record_id"
            elif any(token in key for token in ("dep", "department", "team")) and "team_id" in by_name:
                vals["source_path"] = "team_id.name"
            elif any(token in key for token in ("name", "title", "sap")) and "name" in by_name:
                vals["source_field_id"] = by_name["name"].id
            if vals:
                line.write(vals)
                mapped += 1
        return mapped

    def action_auto_map_parameters(self):
        self.ensure_one()
        mapped = self._auto_map_parameters()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("الربط الذكي"),
                "message": _("تم ربط %s متغيرًا تلقائيًا. راجع البقية قبل التفعيل.", mapped),
                "type": "success" if mapped else "warning",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def action_fetch_template_params(self):
        result = super().action_fetch_template_params()
        # Keep a body copy for previews and map high-confidence variables automatically.
        try:
            wanted = (self.template_name or "").strip().casefold()
            template = next(
                (item for item in self._fetch_wati_templates() if _template_name(item).casefold() == wanted),
                None,
            )
            if template:
                self.template_body = _template_body(template)
        except Exception:
            pass
        self._auto_map_parameters()
        return result

    def _sample_record(self):
        self.ensure_one()
        if not self.model_name or self.model_name not in self.env:
            return self.env[self.model_name].browse() if self.model_name else False
        Model = self.env[self.model_name].sudo()
        records = Model.search([], order="write_date desc, id desc", limit=50)
        for record in records:
            try:
                if self._condition_matches(record):
                    return record
            except Exception:
                continue
        return records[:1]

    def _render_preview(self, record):
        body = self.template_body or ""
        values = {}
        for line in self.parameter_ids.sorted("sequence"):
            if line.param_name:
                values[line.param_name] = self._parameter_value(record, line)
        rendered = body
        for name, value in values.items():
            rendered = re.sub(
                r"{{\s*" + re.escape(str(name)) + r"\s*}}",
                str(value or "—"),
                rendered,
            )
        if not rendered:
            rendered = _("القالب «%s» جاهز. نص القالب غير متاح من WATI للمعاينة النصية.", self.template_name)
        return rendered

    def action_preview_latest_record(self):
        self.ensure_one()
        self._validate_step("trigger")
        if not self.template_name:
            raise UserError(_("اختر قالب WATI أولًا."))
        record = self._sample_record()
        if not record:
            raise UserError(_("لا توجد سجلات في التطبيق المختار لاستخدامها في المعاينة."))
        self.write({
            "preview_text": self._render_preview(record),
            "preview_record_name": record.display_name or str(record.id),
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("تم تحديث المعاينة"),
                "message": _("استخدمنا السجل: %s", record.display_name),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def action_send_test(self):
        self.ensure_one()
        phone = self._normalize_phone(self.test_phone)
        if not phone:
            raise UserError(_("اكتب رقم اختبار صحيحًا أولًا."))
        self._validate_activation()
        record = self._sample_record()
        if not record:
            raise UserError(_("لا توجد سجلات مناسبة لاستخدامها في الاختبار."))
        custom_params = [
            {"name": line.param_name, "value": self._parameter_value(record, line)}
            for line in self.parameter_ids.sorted("sequence") if line.param_name
        ]
        success = self.with_context(wati_test=True)._send_template(record, phone, custom_params)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("إرسال تجريبي"),
                "message": _("تم إرسال الرسالة التجريبية إلى %s", phone) if success else _("فشل الإرسال التجريبي؛ راجع سجل الأتمتة."),
                "type": "success" if success else "danger",
                "sticky": not success,
            },
        }

    def _log_values(self, record, status, phone="", error_message="", response_excerpt=""):
        vals = super()._log_values(record, status, phone=phone, error_message=error_message, response_excerpt=response_excerpt)
        vals["is_test"] = bool(self.env.context.get("wati_test"))
        return vals

    @api.model
    def _upgrade_automation_ux(self):
        existing = self.sudo().search([("active", "=", True)])
        if existing:
            existing.write({"setup_step": "review"})
        return True


class WatiAutomationParameterUX(models.Model):
    _inherit = "wati.automation.parameter"

    mapping_summary = fields.Char(string="الربط", compute="_compute_mapping_summary")

    @api.depends("source_type", "source_field_id", "source_path", "static_value")
    def _compute_mapping_summary(self):
        for line in self:
            if line.source_type == "record_id":
                line.mapping_summary = "✅ رقم السجل"
            elif line.source_type == "record_name":
                line.mapping_summary = "✅ اسم السجل"
            elif line.source_type == "static":
                line.mapping_summary = "✅ ثابت" if (line.static_value or "").strip() else "⚠️ أدخل قيمة"
            elif line.source_field_id:
                line.mapping_summary = "✅ " + (line.source_field_id.field_description or line.source_field_id.name)
            elif (line.source_path or "").strip():
                line.mapping_summary = "✅ " + line.source_path
            else:
                line.mapping_summary = "⚠️ يحتاج ربط"


class WatiAutomationLogUX(models.Model):
    _inherit = "wati.automation.log"

    is_test = fields.Boolean(string="تجريبي", default=False, readonly=True, index=True)


class WatiAutomationValueChoice(models.TransientModel):
    _name = "wati.automation.value.choice"
    _description = "WATI Automation Target Value Choice"
    _order = "label, id"

    rule_id = fields.Many2one("wati.automation.rule", required=True, ondelete="cascade")
    label = fields.Char(string="القيمة", required=True)
    value = fields.Char(string="القيمة التقنية", required=True)

    def action_select(self):
        self.ensure_one()
        self.rule_id.write({"target_value": self.label})
        return {
            "type": "ir.actions.act_window",
            "name": self.rule_id.name,
            "res_model": "wati.automation.rule",
            "res_id": self.rule_id.id,
            "view_mode": "form",
            "target": "current",
        }


class WatiAutomationTemplateChoice(models.TransientModel):
    _name = "wati.automation.template.choice"
    _description = "WATI Automation Template Choice"
    _order = "name, id"

    rule_id = fields.Many2one("wati.automation.rule", required=True, ondelete="cascade")
    name = fields.Char(string="القالب", required=True)
    status = fields.Char(string="الحالة")
    category = fields.Char(string="التصنيف")
    body = fields.Text(string="المعاينة")

    def action_select(self):
        self.ensure_one()
        rule = self.rule_id
        rule.write({"template_name": self.name, "template_body": self.body or False})
        # Fetch exact params from WATI and auto-map what can be inferred safely.
        rule.action_fetch_template_params()
        return {
            "type": "ir.actions.act_window",
            "name": rule.name,
            "res_model": "wati.automation.rule",
            "res_id": rule.id,
            "view_mode": "form",
            "target": "current",
        }
