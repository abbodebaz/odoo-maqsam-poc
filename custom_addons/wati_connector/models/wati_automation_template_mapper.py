from odoo import api, fields, models


def _is_parameter_mapped(line):
    return bool(
        line.source_type in ("record_id", "record_name")
        or (line.source_type == "static" and (line.static_value or "").strip())
        or (
            line.source_type == "field"
            and (line.source_field_id or (line.source_path or "").strip())
        )
    )


class WatiAutomationRuleTemplateMapper(models.Model):
    _inherit = "wati.automation.rule"

    template_parameter_count = fields.Integer(
        string="عدد متغيرات القالب",
        compute="_compute_template_mapping_progress",
    )
    template_mapped_count = fields.Integer(
        string="المتغيرات المربوطة",
        compute="_compute_template_mapping_progress",
    )
    template_mapping_state = fields.Selection(
        [
            ("empty", "لا توجد متغيرات"),
            ("partial", "يحتاج ربط"),
            ("ready", "جاهز"),
        ],
        string="حالة ربط القالب",
        compute="_compute_template_mapping_progress",
    )
    template_mapping_progress = fields.Char(
        string="تقدم ربط القالب",
        compute="_compute_template_mapping_progress",
    )

    @api.depends(
        "parameter_ids",
        "parameter_ids.source_type",
        "parameter_ids.source_field_id",
        "parameter_ids.source_path",
        "parameter_ids.static_value",
    )
    def _compute_template_mapping_progress(self):
        for rule in self:
            total = len(rule.parameter_ids)
            mapped = sum(1 for line in rule.parameter_ids if _is_parameter_mapped(line))
            rule.template_parameter_count = total
            rule.template_mapped_count = mapped
            if not total:
                rule.template_mapping_state = "empty"
                rule.template_mapping_progress = "لا توجد متغيرات في هذا القالب"
            elif mapped == total:
                rule.template_mapping_state = "ready"
                rule.template_mapping_progress = f"{mapped} من {total} جاهزة"
            else:
                rule.template_mapping_state = "partial"
                rule.template_mapping_progress = f"تم ربط {mapped} من {total}"


class WatiAutomationParameterTemplateMapper(models.Model):
    _inherit = "wati.automation.parameter"

    template_variable_label = fields.Char(
        string="متغير الرسالة",
        compute="_compute_template_variable_label",
    )

    @api.depends("sequence", "param_name")
    def _compute_template_variable_label(self):
        for line in self:
            name = (line.param_name or "").strip()
            if name.isdigit():
                token = "{{%s}}" % name
                line.template_variable_label = token
                continue
            position = max(1, int((line.sequence or 10) / 10))
            token = "{{%s}}" % position
            line.template_variable_label = f"{token}  ·  {name}" if name else token
