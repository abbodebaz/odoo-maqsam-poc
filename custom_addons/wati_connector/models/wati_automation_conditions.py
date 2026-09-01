from odoo import api, fields, models
from odoo.exceptions import ValidationError


_EXTRA_OPERATORS = [
    ("eq", "يساوي"),
    ("ne", "لا يساوي"),
    ("contains", "يحتوي"),
    ("gt", "أكبر من"),
    ("gte", "أكبر من أو يساوي"),
    ("lt", "أقل من"),
    ("lte", "أقل من أو يساوي"),
    ("is_set", "له قيمة"),
    ("is_not_set", "بدون قيمة"),
]

_TRUE_VALUES = {"1", "true", "yes", "y", "on", "نعم", "صح", "صحيح"}
_FALSE_VALUES = {"0", "false", "no", "n", "off", "لا", "خطأ", "غلط"}


class WatiAutomationCondition(models.Model):
    _name = "wati.automation.condition"
    _description = "WATI Automation Extra Condition"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    rule_id = fields.Many2one(
        "wati.automation.rule",
        string="القاعدة",
        required=True,
        ondelete="cascade",
        index=True,
    )
    model_id = fields.Many2one(
        "ir.model",
        related="rule_id.model_id",
        store=True,
        readonly=True,
    )
    field_id = fields.Many2one(
        "ir.model.fields",
        string="الحقل",
        required=True,
        ondelete="cascade",
        domain="[('model_id', '=', model_id), ('store', '=', True)]",
    )
    operator = fields.Selection(
        _EXTRA_OPERATORS,
        string="الشرط",
        required=True,
        default="eq",
    )
    target_value = fields.Char(string="القيمة")

    @api.constrains("field_id", "model_id")
    def _check_field_model(self):
        for line in self:
            if line.field_id and line.model_id and line.field_id.model_id != line.model_id:
                raise ValidationError("الحقل الإضافي لا ينتمي إلى التطبيق المختار في الأتمتة.")


class WatiAutomationRuleExtraConditions(models.Model):
    _inherit = "wati.automation.rule"

    condition_ids = fields.One2many(
        "wati.automation.condition",
        "rule_id",
        string="شروط إضافية",
        copy=True,
    )

    def _extra_condition_matches(self, record, condition):
        field_name = condition.field_id.name
        if not field_name or field_name not in record._fields:
            return False

        raw = record[field_name]
        op = condition.operator
        if op == "is_set":
            return bool(raw)
        if op == "is_not_set":
            return not bool(raw)

        target = str(condition.target_value or "").strip()
        field = record._fields[field_name]
        if field.type == "boolean" and op in ("eq", "ne"):
            folded = target.casefold()
            if folded in _TRUE_VALUES:
                wanted = True
            elif folded in _FALSE_VALUES:
                wanted = False
            else:
                return False
            return bool(raw) == wanted if op == "eq" else bool(raw) != wanted

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

    def _condition_matches(self, record):
        self.ensure_one()
        if not super()._condition_matches(record):
            return False
        for condition in self.condition_ids.sorted("sequence"):
            if not self._extra_condition_matches(record, condition):
                return False
        return True
