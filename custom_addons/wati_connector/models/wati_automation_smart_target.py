from odoo import _, api, fields, models


_SMART_TEXT_VALUE_HINTS = (
    "stage",
    "status",
    "state",
    "step",
    "phase",
)


class WatiAutomationRuleSmartTarget(models.Model):
    _inherit = "wati.automation.rule"

    smart_target_metadata = fields.Json(
        string="Smart value settings",
        compute="_compute_smart_target_metadata",
        copy=False,
    )

    def _smart_target_distinct_text_values(self, field_record, limit=50):
        """Suggest live values for state-like Char fields without hard-coding models.

        Some custom Odoo apps store workflow stages/statuses as plain Char fields
        instead of Selection/Many2one fields. For automation setup, surface the
        distinct values already present in readable records while still allowing
        the user to type a new value manually.
        """
        if not field_record or field_record.model not in self.env:
            return []

        haystack = " ".join(
            filter(
                None,
                [
                    field_record.name or "",
                    field_record.field_description or "",
                ],
            )
        ).casefold()
        if not any(token in haystack for token in _SMART_TEXT_VALUE_HINTS):
            return []

        Model = self.env[field_record.model]
        runtime_field = Model._fields.get(field_record.name)
        if not runtime_field or getattr(runtime_field, "type", "") != "char":
            return []

        try:
            records = Model.search(
                [(field_record.name, "!=", False)],
                order="id desc",
                limit=250,
            )
        except Exception:
            return []

        values = []
        seen = set()
        for record in records:
            try:
                raw = record[field_record.name]
            except Exception:
                continue
            value = str(raw or "").strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            values.append(value)
            if len(values) >= limit:
                break
        return values

    def _smart_target_metadata_for_field(self, field_record):
        metadata = {
            "mode": "input",
            "field_type": "char",
            "input_type": "text",
            "placeholder": _("Type the required value"),
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
                "placeholder": _("Choose the value"),
                "options": [
                    {"value": str(label), "label": str(label), "technical_value": str(value)}
                    for value, label in choices
                ],
            })
            return metadata

        if field_type == "boolean":
            metadata.update({
                "mode": "select",
                "placeholder": _("Choose yes or no"),
                "options": [
                    {"value": "True", "label": _("Yes")},
                    {"value": "False", "label": _("No")},
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
                "placeholder": _("Choose or type the value"),
                "options": options,
                "relation": relation or "",
            })
            return metadata

        if field_type in ("integer", "float", "monetary"):
            metadata.update({
                "input_type": "number",
                "placeholder": _("Type a number"),
            })
        elif field_type == "date":
            metadata.update({
                "input_type": "date",
                "placeholder": _("Choose the date"),
            })
        elif field_type == "datetime":
            metadata.update({
                "input_type": "datetime-local",
                "placeholder": _("Choose date and time"),
            })
        elif field_type == "char":
            live_values = self._smart_target_distinct_text_values(field_record)
            if live_values:
                metadata.update({
                    "mode": "suggest",
                    "input_type": "text",
                    "placeholder": _("Choose an existing value or type a new one"),
                    "options": [
                        {"value": value, "label": value}
                        for value in live_values
                    ],
                })
            else:
                metadata.update({
                    "input_type": "text",
                    "placeholder": _("Type the required value"),
                })
        elif field_type in ("text", "html"):
            metadata.update({
                "input_type": "text",
                "placeholder": _("Type the required value"),
            })
        else:
            metadata.update({
                "input_type": "text",
                "placeholder": _("Type the required value"),
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
