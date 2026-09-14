from odoo import _, api, fields, models


_SMART_TEXT_VALUE_HINTS = (
    "stage",
    "status",
    "state",
    "step",
    "phase",
)


class WatiOtpFlowSmartTarget(models.Model):
    _inherit = "wati.otp.flow"

    smart_target_metadata = fields.Json(
        string="Smart trigger value settings",
        compute="_compute_smart_target_metadata",
        copy=False,
    )

    def _smart_trigger_distinct_text_values(self, field_record, limit=50):
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

        Model = self.env[field_record.model]
        runtime_field = Model._fields.get(field_record.name)
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
                    {"value": str(value), "label": str(label)}
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

        if field_type == "many2one":
            relation = getattr(runtime_field, "comodel_name", False) or field_record.relation
            options = []
            if relation and relation in self.env:
                try:
                    pairs = self.env[relation].sudo().name_search(
                        name="",
                        domain=[],
                        operator="ilike",
                        limit=250,
                    )
                    seen_labels = set()
                    for record_id, label in pairs:
                        display = str(label or record_id).strip()
                        key = display.casefold()
                        if not display or key in seen_labels:
                            continue
                        seen_labels.add(key)
                        options.append({
                            "value": str(record_id),
                            "label": display,
                            "record_id": record_id,
                        })
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
            live_values = self._smart_trigger_distinct_text_values(field_record)
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
        elif field_type in ("text", "html"):
            metadata.update({
                "input_type": "text",
                "placeholder": _("Type the required value"),
            })
        return metadata

    @api.depends("trigger_field_id")
    def _compute_smart_target_metadata(self):
        for flow in self:
            flow.smart_target_metadata = flow._smart_target_metadata_for_field(flow.trigger_field_id)
