from odoo import api, fields, models


def _clean(value):
    if value in (None, False):
        return ""
    return str(value).strip()


class WatiOtpPostActionSmartValue(models.Model):
    _inherit = "wati.otp.post.action"

    smart_target_metadata = fields.Json(compute="_compute_smart_target_metadata")

    @api.depends("field_id", "model_id")
    def _compute_smart_target_metadata(self):
        for action in self:
            action.smart_target_metadata = action._build_smart_target_metadata()

    def _build_smart_target_metadata(self):
        self.ensure_one()
        field_record = self.field_id
        if not field_record:
            return {
                "mode": "input",
                "input_type": "text",
                "placeholder": "Choose a field first",
                "options": [],
            }

        field_type = field_record.ttype
        if field_type == "boolean":
            return {
                "mode": "select",
                "placeholder": "Choose Yes or No",
                "options": [
                    {"value": "True", "label": "Yes"},
                    {"value": "False", "label": "No"},
                ],
            }

        if field_type == "selection":
            selection = []
            model_name = self.model_id.model if self.model_id else False
            if model_name and model_name in self.env:
                field = self.env[model_name]._fields.get(field_record.name)
                if field:
                    try:
                        selection = field._description_selection(self.env)
                    except Exception:
                        raw = getattr(field, "selection", None)
                        if isinstance(raw, (list, tuple)):
                            selection = raw
            return {
                "mode": "select",
                "placeholder": "Choose the new value",
                "options": [
                    {"value": _clean(key), "label": _clean(label) or _clean(key)}
                    for key, label in selection
                ],
            }

        if field_type == "many2one":
            relation = field_record.relation
            options = []
            if relation and relation in self.env:
                try:
                    rows = self.env[relation].sudo().name_search(name="", args=[], operator="ilike", limit=100)
                except Exception:
                    rows = []
                seen = set()
                for record_id, label in rows:
                    key = str(record_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    options.append({"value": key, "label": _clean(label) or key})
            return {
                "mode": "select",
                "placeholder": "Choose the related record",
                "options": options,
            }

        if field_type in ("integer", "float"):
            return {
                "mode": "input",
                "input_type": "number",
                "placeholder": "Enter the new number",
                "options": [],
            }

        return {
            "mode": "input",
            "input_type": "text",
            "placeholder": "Enter the new value",
            "options": [],
        }

    @api.onchange("field_id")
    def _onchange_smart_value_field(self):
        for action in self:
            action.value = False
