from odoo import api, fields, models


_SIMPLE_TYPES = {
    "char", "text", "selection", "boolean", "integer", "float",
    "monetary", "date", "datetime",
}
_SKIP_FIELDS = {
    "id", "create_uid", "create_date", "write_uid", "write_date", "display_name",
    "__last_update",
}
_RELATION_HINTS = (
    "partner", "customer", "client", "contact", "task", "sale", "order",
    "invoice", "company", "user",
)


class WatiOtpVariableBindingSmartFields(models.Model):
    _inherit = "wati.otp.variable.binding"

    smart_target_metadata = fields.Json(
        string="Smart Odoo field options",
        compute="_compute_smart_target_metadata",
    )

    @api.model
    def _relation_score(self, field):
        haystack = f"{getattr(field, 'name', '')} {getattr(field, 'string', '')}".casefold()
        return 0 if any(token in haystack for token in _RELATION_HINTS) else 5

    def _field_path_options(self, max_depth=2, limit=120):
        self.ensure_one()
        model_name = self.flow_id.model_name if self.flow_id else False
        if not model_name or model_name not in self.env:
            return []

        options = []
        seen = set()

        def add(path, label, depth, score):
            if path and path not in seen and len(options) < limit:
                seen.add(path)
                options.append({
                    "value": path,
                    "label": label,
                    "depth": depth,
                    "score": score,
                })

        def walk(current_model, prefix="", label_prefix="", depth=0, visited=None):
            if current_model not in self.env or len(options) >= limit:
                return
            visited = set(visited or set())
            if current_model in visited and depth:
                return
            visited.add(current_model)
            Model = self.env[current_model]

            simple_fields = [
                field for field in Model._fields.values()
                if field.name not in _SKIP_FIELDS
                and getattr(field, "type", "") in _SIMPLE_TYPES
            ]
            simple_fields.sort(key=lambda field: (getattr(field, "string", "") or field.name).casefold())
            for field in simple_fields:
                field_label = getattr(field, "string", False) or field.name
                path = f"{prefix}.{field.name}" if prefix else field.name
                label = f"{label_prefix} → {field_label}" if label_prefix else field_label
                add(path, label, depth, depth * 20)

            if depth >= max_depth:
                return

            relations = [
                field for field in Model._fields.values()
                if getattr(field, "type", "") == "many2one"
                and getattr(field, "comodel_name", False)
                and field.name not in _SKIP_FIELDS
            ]
            relations.sort(key=lambda field: (self._relation_score(field), (getattr(field, "string", "") or field.name).casefold()))
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

    @api.depends("flow_id.model_id", "source_type")
    def _compute_smart_target_metadata(self):
        for line in self:
            if line.source_type != "record" or not line.flow_id.model_id:
                line.smart_target_metadata = {
                    "mode": "empty",
                    "placeholder": "Choose Odoo field",
                    "options": [],
                }
                continue
            options = line._field_path_options()
            line.smart_target_metadata = {
                "mode": "select" if options else "input",
                "placeholder": "Choose an Odoo field — no typing required",
                "options": [
                    {"value": item["value"], "label": item["label"]}
                    for item in options
                ],
            }
