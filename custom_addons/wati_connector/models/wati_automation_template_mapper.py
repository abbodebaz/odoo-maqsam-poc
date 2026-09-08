from odoo import api, fields, models

from .wati_automation_improvements import _dedupe_names


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

    def _sync_template_parameters(self, param_names):
        """Reconcile template rows safely while preserving same-name mappings."""
        self.ensure_one()
        desired = _dedupe_names(param_names)
        desired_keys = {name.casefold() for name in desired}
        existing_by_key = {}
        stale_or_duplicate = self.env["wati.automation.parameter"]

        for line in self.parameter_ids.sorted(lambda item: (item.sequence, item.id)):
            key = (line.param_name or "").strip().casefold()
            if not key or key not in desired_keys or key in existing_by_key:
                stale_or_duplicate |= line
                continue
            existing_by_key[key] = line

        if stale_or_duplicate:
            stale_or_duplicate.unlink()

        created = 0
        for index, name in enumerate(desired, start=1):
            key = name.casefold()
            line = existing_by_key.get(key)
            vals = {"param_name": name, "sequence": index * 10}
            if line:
                line.write(vals)
            else:
                vals.update({
                    "rule_id": self.id,
                    "source_type": "field",
                })
                self.env["wati.automation.parameter"].create(vals)
                created += 1
        return created

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
