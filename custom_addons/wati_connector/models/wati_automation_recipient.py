from odoo import _, api, fields, models
from odoo.exceptions import UserError


_PHONE_TOKENS = (
    "mobile", "phone", "whatsapp", "whats_app", "telephone", "tel",
    "جوال", "هاتف", "واتساب",
)
_RELATION_HINTS = (
    "partner", "customer", "client", "contact", "commercial_partner",
    "عميل", "جهة اتصال",
)


class WatiAutomationRecipient(models.Model):
    _inherit = "wati.automation.rule"

    recipient_mode = fields.Selection(
        [
            ("auto", "رقم العميل تلقائيًا — موصى به"),
            ("direct", "رقم من السجل"),
            ("related", "رقم من سجل مرتبط"),
        ],
        string="طريقة اختيار المستلم",
        default="auto",
        copy=True,
    )
    recipient_advanced_path = fields.Char(
        string="مسار رقم مخصص",
        copy=True,
        help="للاستخدام المتقدم فقط. مثال: partner_id.mobile",
    )
    smart_recipient_metadata = fields.Json(
        string="خيارات المستلم الذكية",
        compute="_compute_smart_recipient_state",
    )
    recipient_summary = fields.Char(
        string="المستلم",
        compute="_compute_smart_recipient_state",
    )
    recipient_preview_note = fields.Char(
        string="معاينة المستلم",
        compute="_compute_smart_recipient_state",
    )

    @api.model
    def _is_phone_like_field(self, field):
        if getattr(field, "type", "") not in ("char", "text"):
            return False
        haystack = f"{getattr(field, 'name', '')} {getattr(field, 'string', '')}".casefold()
        return any(token.casefold() in haystack for token in _PHONE_TOKENS)

    @api.model
    def _phone_field_score(self, field):
        name = (getattr(field, "name", "") or "").casefold()
        if name == "mobile":
            return 0
        if name == "phone":
            return 1
        if "whatsapp" in name:
            return 2
        if "mobile" in name:
            return 3
        if "phone" in name:
            return 4
        return 8

    @api.model
    def _relation_score(self, field):
        haystack = f"{getattr(field, 'name', '')} {getattr(field, 'string', '')}".casefold()
        return 0 if any(token.casefold() in haystack for token in _RELATION_HINTS) else 5

    def _recipient_path_options(self, max_depth=2, limit=80):
        """Discover useful phone paths from the selected Odoo model.

        This deliberately reads Odoo model metadata instead of hard-coding CRM,
        Helpdesk, Sales, Project, or custom app names.
        """
        self.ensure_one()
        model_name = self.model_id.model if self.model_id else False
        if not model_name or model_name not in self.env:
            return []

        options = []
        seen_paths = set()

        def add_option(path, label, depth, score):
            if not path or path in seen_paths or len(options) >= limit:
                return
            seen_paths.add(path)
            options.append({
                "value": path,
                "label": label,
                "depth": depth,
                "score": score,
            })

        def walk(current_model_name, prefix="", label_prefix="", depth=0, visited=None):
            if len(options) >= limit or current_model_name not in self.env:
                return
            visited = set(visited or set())
            if current_model_name in visited and depth:
                return
            visited.add(current_model_name)
            Model = self.env[current_model_name]

            phone_fields = [
                field for field in Model._fields.values()
                if self._is_phone_like_field(field)
            ]
            phone_fields.sort(key=self._phone_field_score)
            for field in phone_fields:
                field_label = getattr(field, "string", False) or field.name
                path = f"{prefix}.{field.name}" if prefix else field.name
                label = f"{label_prefix} → {field_label}" if label_prefix else field_label
                add_option(path, label, depth, depth * 20 + self._phone_field_score(field))

            if depth >= max_depth:
                return

            relations = [
                field for field in Model._fields.values()
                if getattr(field, "type", "") == "many2one"
                and getattr(field, "comodel_name", False)
                and field.name not in ("create_uid", "write_uid")
            ]
            relations.sort(key=self._relation_score)
            for field in relations:
                relation = field.comodel_name
                if relation not in self.env:
                    continue
                relation_label = getattr(field, "string", False) or field.name
                path_prefix = f"{prefix}.{field.name}" if prefix else field.name
                next_label = f"{label_prefix} → {relation_label}" if label_prefix else relation_label
                walk(relation, path_prefix, next_label, depth + 1, visited)

        walk(model_name)
        return sorted(options, key=lambda item: (item["score"], item["label"].casefold()))[:limit]

    @api.depends(
        "model_id", "recipient_mode", "recipient_path", "recipient_field_id",
        "recipient_advanced_path",
    )
    def _compute_smart_recipient_state(self):
        for rule in self:
            mode = rule.recipient_mode or "auto"
            options = rule._recipient_path_options() if rule.model_id else []
            direct = [item for item in options if item["depth"] == 0]
            related = [item for item in options if item["depth"] > 0]
            visible = direct if mode == "direct" else related if mode == "related" else options

            rule.smart_recipient_metadata = {
                "mode": "select" if visible else "empty",
                "placeholder": (
                    "اختر حقل الهاتف من السجل"
                    if mode == "direct"
                    else "اختر الرقم من سجل مرتبط"
                ),
                "options": [
                    {"value": item["value"], "label": item["label"]}
                    for item in visible
                ],
            }

            selected = next(
                (item for item in options if item["value"] == (rule.recipient_path or "")),
                None,
            )
            if rule.recipient_advanced_path:
                rule.recipient_summary = _("مسار رقم مخصص")
                rule.recipient_preview_note = _("سيتم استخدام المسار المتقدم الذي حدده المسؤول.")
            elif mode == "auto":
                rule.recipient_summary = _("رقم العميل تلقائيًا")
                if options:
                    labels = "، ".join(item["label"] for item in options[:3])
                    rule.recipient_preview_note = _("سيبحث النظام تلقائيًا بالترتيب الأنسب، مثل: %s", labels)
                else:
                    rule.recipient_preview_note = _("لم نجد حقل هاتف واضحًا بعد؛ يمكنك اختيار مسار متقدم إذا لزم.")
            elif selected:
                rule.recipient_summary = selected["label"]
                rule.recipient_preview_note = _("سيتم إرسال الرسالة إلى: %s", selected["label"])
            else:
                rule.recipient_summary = _("اختر رقم المستلم")
                rule.recipient_preview_note = (
                    _("اختر حقل هاتف من نفس السجل.")
                    if mode == "direct"
                    else _("اختر حقل هاتف من سجل مرتبط.")
                )

    @api.onchange("recipient_mode")
    def _onchange_recipient_mode(self):
        for rule in self:
            rule.recipient_path = False
            rule.recipient_field_id = False

    @api.onchange("recipient_path")
    def _onchange_smart_recipient_path(self):
        for rule in self:
            if (rule.recipient_mode or "auto") == "direct" and rule.model_id and rule.recipient_path:
                field = self.env["ir.model.fields"].sudo().search([
                    ("model_id", "=", rule.model_id.id),
                    ("name", "=", rule.recipient_path),
                ], limit=1)
                rule.recipient_field_id = field
            elif (rule.recipient_mode or "auto") == "related":
                rule.recipient_field_id = False

    def _recipient_phone(self, record):
        self.ensure_one()
        advanced = (self.recipient_advanced_path or "").strip()
        if advanced:
            value = self._resolve_path(record, advanced)
            return self._normalize_phone(value) if value else ""

        mode = self.recipient_mode or "auto"
        if mode in ("direct", "related"):
            path = (self.recipient_path or "").strip()
            if not path:
                return ""
            value = self._resolve_path(record, path)
            return self._normalize_phone(value) if value else ""

        # Preserve pre-existing rules that already have an explicit recipient.
        if self.recipient_path or self.recipient_field_id:
            return super()._recipient_phone(record)

        for option in self._recipient_path_options():
            value = self._resolve_path(record, option["value"])
            if value:
                normalized = self._normalize_phone(value)
                if normalized:
                    return normalized
        return super()._recipient_phone(record)

    def _validate_step(self, step=None):
        result = super()._validate_step(step)
        step = step or self.setup_step
        if step == "recipient":
            mode = self.recipient_mode or "auto"
            if mode in ("direct", "related") and not (self.recipient_path or "").strip():
                raise UserError(_("اختر رقم المستلم قبل المتابعة."))
        return result

    @api.depends(
        "recipient_mode", "recipient_path", "recipient_field_id", "recipient_advanced_path"
    )
    def _compute_ux_state(self):
        super()._compute_ux_state()
        for rule in self:
            if not rule.human_summary:
                continue
            if rule.recipient_field_id:
                old_recipient = rule.recipient_field_id.field_description or rule.recipient_field_id.name
            elif rule.recipient_path:
                old_recipient = rule.recipient_path
            else:
                old_recipient = "رقم العميل تلقائيًا"
            if rule.recipient_summary:
                rule.human_summary = rule.human_summary.replace(
                    f"إلى {old_recipient}", f"إلى {rule.recipient_summary}", 1
                )

            if (rule.recipient_mode or "auto") == "auto" and rule._recipient_path_options():
                lines = [
                    line for line in (rule.readiness_message or "").splitlines()
                    if "سيبحث النظام تلقائيًا عن mobile / phone / رقم العميل المرتبط" not in line
                ]
                rule.readiness_message = "\n".join(lines)
                if rule.readiness_state == "warning" and not any(line.startswith("⚠️") for line in lines):
                    rule.readiness_state = "ready"
