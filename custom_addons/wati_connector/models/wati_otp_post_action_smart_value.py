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

    def _relation_options(self, field_record, limit=200):
        """Return stable, user-visible choices for a many2one post action.

        Do not rely on ``name_search('', ...)`` alone. Some custom Odoo models
        override name_search and return no rows for an empty term even though
        records exist. That made fields such as CRM Stage render an empty
        dropdown. Search the relation first, then use name_get/display_name.
        """
        self.ensure_one()
        relation = field_record.relation
        if not relation or relation not in self.env:
            return []

        Target = self.env[relation].sudo().with_context(active_test=False)
        try:
            records = Target.search([], limit=limit)
        except Exception:
            records = Target.browse()

        rows = []
        if records:
            try:
                rows = records.name_get()
            except Exception:
                rows = [(record.id, record.display_name) for record in records]

        # Last-resort compatibility for unusual relation models.
        if not rows:
            try:
                rows = Target.name_search(name="", args=[], operator="ilike", limit=limit)
            except Exception:
                rows = []

        options = []
        seen_ids = set()
        for record_id, label in rows:
            if not record_id or record_id in seen_ids:
                continue
            seen_ids.add(record_id)
            options.append(
                {
                    "value": str(record_id),
                    "label": _clean(label) or str(record_id),
                }
            )
        return options

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
            options = self._relation_options(field_record)
            if options:
                return {
                    "mode": "select",
                    "placeholder": "Choose the related record",
                    "options": options,
                }
            # Never leave the administrator trapped in a dead dropdown. The
            # execution layer already accepts an exact visible name or ID.
            return {
                "mode": "input",
                "input_type": "text",
                "placeholder": "Enter the exact visible value or record ID",
                "options": [],
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
