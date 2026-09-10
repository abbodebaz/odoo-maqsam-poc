import json

from odoo import api, models

from .wati_automation_improvements import _template_body_tokens
from .wati_automation_template_switch import _load_param_names


class WatiAutomationRuleTemplateInvariant(models.Model):
    _inherit = "wati.automation.rule"

    def _current_template_param_names(self):
        self.ensure_one()
        body_tokens = _template_body_tokens({"body": self.template_body or ""})
        cached_names = _load_param_names(self.template_param_names_json)
        if body_tokens:
            if cached_names and len(cached_names) == len(body_tokens):
                return cached_names
            return body_tokens
        return cached_names

    def _reconcile_current_template_parameters(self):
        for rule in self:
            if not rule.template_name:
                if rule.parameter_ids:
                    rule.parameter_ids.unlink()
                continue
            names = rule._current_template_param_names()
            rule._sync_template_parameters(names)
        return True

    def write(self, vals):
        old_names = {rule.id: (rule.template_name or "") for rule in self}
        result = super().write(vals)

        if "template_name" in vals:
            for rule in self:
                if old_names.get(rule.id, "") != (rule.template_name or ""):
                    # A template owns its mappings exclusively. Any template
                    # change must replace, never append to, the previous rows.
                    if rule.parameter_ids:
                        rule.parameter_ids.unlink()
                    rule._reconcile_current_template_parameters()
        return result

    @api.model
    def _repair_template_parameter_invariants(self):
        """Repair legacy rules that accumulated mappings from old templates."""
        rules = self.sudo().search([("template_name", "!=", False)])
        repaired = 0
        for rule in rules:
            before = tuple(rule.parameter_ids.ids)
            rule._reconcile_current_template_parameters()
            after = tuple(rule.parameter_ids.ids)
            if before != after:
                repaired += 1
        return repaired
