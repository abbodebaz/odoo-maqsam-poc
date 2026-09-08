from odoo import _, api, fields, models


_EVENT_OPERATOR_LABELS = {
    "eq": "يساوي",
    "ne": "لا يساوي",
    "contains": "يحتوي على",
    "gt": "أكبر من",
    "gte": "أكبر من أو يساوي",
    "lt": "أقل من",
    "lte": "أقل من أو يساوي",
    "is_set": "تصبح له قيمة",
    "is_not_set": "يصبح فارغًا",
}


class WatiAutomationRuleBuilder(models.Model):
    _inherit = "wati.automation.rule"

    event_summary = fields.Char(
        string="ملخص الحدث",
        compute="_compute_event_summary",
        help="وصف مبسط للحدث الذي سيبدأ الأتمتة.",
    )

    @api.depends(
        "model_id",
        "trigger_field_id",
        "condition_operator",
        "target_value",
    )
    def _compute_event_summary(self):
        for rule in self:
            if not rule.model_id:
                rule.event_summary = "اختر الجزء الذي تريد مراقبته من Odoo."
                continue

            model_label = rule.model_id.name or rule.model_id.model or _("السجل")
            if not rule.trigger_field_id:
                rule.event_summary = _(
                    "سنراقب %(model)s. اختر المعلومة التي تبدأ الحدث.",
                    model=model_label,
                )
                continue

            field_label = (
                rule.trigger_field_id.field_description
                or rule.trigger_field_id.name
                or _("الحقل")
            )
            operator = _EVENT_OPERATOR_LABELS.get(
                rule.condition_operator,
                rule.condition_operator or "",
            )
            target = (rule.target_value or "").strip()

            if rule.condition_operator in ("is_set", "is_not_set"):
                rule.event_summary = _(
                    "عندما %(field)s %(operator)s في %(model)s.",
                    field=field_label,
                    operator=operator,
                    model=model_label,
                )
            elif target:
                rule.event_summary = _(
                    "عندما %(field)s %(operator)s «%(target)s» في %(model)s.",
                    field=field_label,
                    operator=operator,
                    target=target,
                    model=model_label,
                )
            else:
                rule.event_summary = _(
                    "سنراقب %(field)s في %(model)s. أكمل الشرط والقيمة المطلوبة.",
                    field=field_label,
                    model=model_label,
                )

    @api.onchange("model_id")
    def _onchange_builder_model_id(self):
        """Keep dependent selections valid when the user changes the Odoo model."""
        for rule in self:
            if rule.trigger_field_id and rule.trigger_field_id.model_id != rule.model_id:
                rule.trigger_field_id = False
                rule.target_value = False
            if rule.recipient_field_id and rule.recipient_field_id.model_id != rule.model_id:
                rule.recipient_field_id = False

    @api.onchange("trigger_field_id")
    def _onchange_builder_trigger_field_id(self):
        for rule in self:
            rule.target_value = False

    def action_apply_named_preset(self):
        self.ensure_one()
        preset_key = (self.env.context.get("wati_preset_key") or "").strip()
        if not preset_key:
            return self.action_apply_preset()
        self.preset_key = preset_key
        return self.action_apply_preset()

    def action_start_custom_builder(self):
        self.ensure_one()
        self.write({"preset_key": False, "setup_step": "trigger"})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("إعداد مخصص"),
                "message": _("ابدأ باختيار التطبيق والحقل والقيمة التي تريد مراقبتها."),
                "type": "info",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }
