from odoo import _, api, fields, models


class WatiAutomationRuleSmartTarget(models.Model):
    _inherit = "wati.automation.rule"

    smart_target_metadata = fields.Json(
        string="إعدادات القيمة الذكية",
        compute="_compute_smart_target_metadata",
        copy=False,
    )

    def _smart_target_metadata_for_field(self, field_record):
        metadata = {
            "mode": "input",
            "field_type": "char",
            "input_type": "text",
            "placeholder": _("اكتب القيمة المطلوبة"),
            "options": [],
        }
        if not field_record or field_record.model not in self.env:
            return metadata

        model = self.env[field_record.model]
        runtime_field = model._fields.get(field_record.name)
        if not runtime_field:
            return metadata

        field_type = getattr(runtime_field, "type", False) or field_record.ttype or "char"
        metadata["field_type"] = field_type

        if field_type == "selection":
            try:
                choices = runtime_field._description_selection(self.env)
            except Exception:
                choices = []
            metadata.update({
                "mode": "select",
                "placeholder": _("اختر القيمة"),
                "options": [
                    {"value": str(label), "label": str(label), "technical_value": str(value)}
                    for value, label in choices
                ],
            })
            return metadata

        if field_type == "boolean":
            metadata.update({
                "mode": "select",
                "placeholder": _("اختر نعم أو لا"),
                "options": [
                    {"value": "True", "label": _("نعم")},
                    {"value": "False", "label": _("لا")},
                ],
            })
            return metadata

        if field_type in ("many2one", "many2many", "one2many"):
            relation = getattr(runtime_field, "comodel_name", False) or field_record.relation
            options = []
            if relation and relation in self.env:
                try:
                    # name_search is the safest generic way to obtain user-facing
                    # values across standard and custom Odoo models. It also fixes
                    # fields such as CRM stage_id where the relation is crm.stage.
                    pairs = self.env[relation].sudo().name_search(
                        name="",
                        domain=[],
                        operator="ilike",
                        limit=250,
                    )
                    options = [
                        {"value": str(label or record_id), "label": str(label or record_id), "record_id": record_id}
                        for record_id, label in pairs
                    ]
                except Exception:
                    options = []
            metadata.update({
                "mode": "suggest" if options else "input",
                "placeholder": _("اختر أو اكتب القيمة"),
                "options": options,
                "relation": relation or "",
            })
            return metadata

        if field_type in ("integer", "float", "monetary"):
            metadata.update({
                "input_type": "number",
                "placeholder": _("اكتب رقمًا"),
            })
        elif field_type == "date":
            metadata.update({
                "input_type": "date",
                "placeholder": _("اختر التاريخ"),
            })
        elif field_type == "datetime":
            metadata.update({
                "input_type": "datetime-local",
                "placeholder": _("اختر التاريخ والوقت"),
            })
        elif field_type in ("char", "text", "html"):
            metadata.update({
                "input_type": "text",
                "placeholder": _("اكتب القيمة المطلوبة"),
            })
        else:
            metadata.update({
                "input_type": "text",
                "placeholder": _("اكتب القيمة المطلوبة"),
            })
        return metadata

    @api.depends("trigger_field_id")
    def _compute_smart_target_metadata(self):
        for rule in self:
            rule.smart_target_metadata = rule._smart_target_metadata_for_field(rule.trigger_field_id)

    def _target_choices(self):
        """Keep the legacy picker compatible with the new generic resolver."""
        self.ensure_one()
        metadata = self._smart_target_metadata_for_field(self.trigger_field_id)
        return [
            (item.get("value", ""), item.get("label", item.get("value", "")))
            for item in metadata.get("options", [])
            if item.get("value") not in (None, "")
        ]
