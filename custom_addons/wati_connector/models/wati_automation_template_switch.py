import json

from odoo import _, fields, models

from .wati_automation_improvements import (
    _template_body,
    _template_body_tokens,
    _template_name,
)
from .wati_automation_template_truth import _canonical_template_param_names


_GENERAL_TEMPLATE_NAMES = {"whatsapp", "wati", "unknown", "none", "null"}


def _load_param_names(raw):
    try:
        values = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(values, list):
        return []
    result = []
    seen = set()
    for value in values:
        name = str(value or "").strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


class WatiAutomationRuleTemplateSwitch(models.Model):
    _inherit = "wati.automation.rule"

    template_param_names_json = fields.Text(
        string="Variables of the selected template",
        copy=False,
        readonly=True,
        help="Internal copy of variables of the same element WATI chosen by the user.",
    )

    def action_pick_template(self):
        """Build choices from exact WATI items and cache their canonical variables.

        The old flow selected a row and then fetched WATI again by template name.
        If WATI returned multiple variants with the same name, the second lookup
        could resolve a different item. Each choice now carries the body and
        canonical variables from the exact item that the user clicked.
        """
        self.ensure_one()
        templates = self._fetch_wati_templates()
        if not templates:
            from odoo.exceptions import UserError

            raise UserError(_("No templates found WhatsApp In an account WATI."))

        Choice = self.env["wati.automation.template.choice"]
        Choice.search([("rule_id", "=", self.id)]).unlink()
        values = []
        for item in templates:
            name = _template_name(item)
            if not name or name.casefold() in _GENERAL_TEMPLATE_NAMES:
                continue
            status = str(
                item.get("status")
                or item.get("approvalStatus")
                or item.get("templateStatus")
                or ""
            ) if isinstance(item, dict) else ""
            category = str(item.get("category") or item.get("type") or "") if isinstance(item, dict) else ""
            param_names = _canonical_template_param_names(item)
            values.append({
                "rule_id": self.id,
                "name": name,
                "status": status,
                "category": category,
                "body": _template_body(item),
                "param_names_json": json.dumps(param_names, ensure_ascii=False),
            })
        if values:
            Choice.create(values)

        return {
            "type": "ir.actions.act_window",
            "name": _("Choose a template WATI"),
            "res_model": "wati.automation.template.choice",
            "view_mode": "list",
            "views": [(self.env.ref("wati_connector.view_wati_automation_template_choice_list").id, "list")],
            "domain": [("rule_id", "=", self.id)],
            "target": "new",
        }

    def action_fetch_template_params(self):
        """Reconcile from the already selected body before any name-only refetch.

        This makes re-sync idempotent and also cleans legacy accumulated rows.
        If the selected body says there is one placeholder, the rule ends with
        exactly one mapping row, regardless of stale metadata or prior templates.
        """
        self.ensure_one()
        if not self.template_body:
            return super().action_fetch_template_params()

        body_tokens = _template_body_tokens({"body": self.template_body})
        cached_names = _load_param_names(self.template_param_names_json)

        if body_tokens:
            if cached_names and len(cached_names) == len(body_tokens):
                param_names = cached_names
            else:
                param_names = body_tokens
        else:
            param_names = cached_names

        created = self._sync_template_parameters(param_names)
        auto_mapped = 0
        auto_mapper = getattr(self, "_auto_map_parameters", None)
        if callable(auto_mapper) and param_names:
            try:
                auto_mapped = auto_mapper()
            except Exception:
                auto_mapped = 0

        parts = [_("Variables are matched to the current template text: %s variable.", len(param_names))]
        if created:
            parts.append(_("has been created %s New link.", created))
        if auto_mapped:
            parts.append(_("been suggested %s Automatic connection.", auto_mapped))

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Template variables have been cleaned and synchronized"),
                "message": " ".join(parts),
                "type": "success" if param_names else "warning",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }


class WatiAutomationTemplateChoiceSwitch(models.TransientModel):
    _inherit = "wati.automation.template.choice"

    param_names_json = fields.Text(readonly=True)

    def action_select(self):
        """Hard-replace the previous template and all of its mapping rows."""
        self.ensure_one()
        rule = self.rule_id
        param_names = _load_param_names(self.param_names_json)
        if not param_names and self.body:
            # Safe fallback: only variables visibly present in this exact body.
            param_names = _canonical_template_param_names({"body": self.body})

        # Template mappings belong to exactly one template. Never append rows
        # from a previous selection to the newly selected template.
        rule.parameter_ids.unlink()
        rule.write({
            "template_name": self.name,
            "template_body": self.body or False,
            "template_param_names_json": json.dumps(param_names, ensure_ascii=False),
            "preview_text": False,
            "preview_record_name": False,
        })
        rule._sync_template_parameters(param_names)

        auto_mapper = getattr(rule, "_auto_map_parameters", None)
        if callable(auto_mapper) and param_names:
            try:
                auto_mapper()
            except Exception:
                pass

        return {
            "type": "ir.actions.act_window",
            "name": rule.name,
            "res_model": "wati.automation.rule",
            "res_id": rule.id,
            "view_mode": "form",
            "target": "current",
        }
