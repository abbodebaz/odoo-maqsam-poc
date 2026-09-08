import json
import logging
import re

from odoo import _, api, models

from .wati_automation_template_switch import _load_param_names


_logger = logging.getLogger(__name__)
_TOKEN_RE = re.compile(r"{{\s*([^{}]+?)\s*}}")


def _tokens_from_body(body):
    """Return unique placeholders exactly as they appear in the visible body.

    The WATI template body is the source of truth.  WATI metadata can contain
    stale parameter names from another revision/template, so metadata is only
    used as a fallback when the body contains no placeholders at all.
    """
    result = []
    seen = set()
    for raw in _TOKEN_RE.findall(body or ""):
        name = str(raw or "").strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


class WatiAutomationRuleTemplateIntegrity(models.Model):
    _inherit = "wati.automation.rule"

    def _integrity_expected_parameter_names(self):
        self.ensure_one()
        body_names = _tokens_from_body(self.template_body or "")
        if body_names:
            return body_names
        # Header/button-only templates may legitimately expose parameters while
        # the BODY has none.  In that special case keep the exact cached list
        # captured from the selected WATI template.
        return _load_param_names(self.template_param_names_json)

    def _hard_rebuild_template_parameters(self, reason="runtime"):
        """Make persisted mapping rows exactly match the current template.

        This deliberately uses a database-level delete for stale rows.  Earlier
        versions only reconciled through ORM recordsets; legacy rows could stay
        cached/persisted and reappear in the form.  The SQL delete makes the
        invariant unambiguous, then ORM is used to preserve/create the expected
        rows and refresh caches.
        """
        Parameter = self.env["wati.automation.parameter"].sudo()

        for rule in self.sudo():
            expected = rule._integrity_expected_parameter_names() if rule.template_name else []
            expected_keys = [name.casefold() for name in expected]
            rows = Parameter.search([("rule_id", "=", rule.id)], order="sequence, id")
            before_names = rows.mapped("param_name")

            keep_by_key = {}
            delete_ids = []
            for row in rows:
                key = (row.param_name or "").strip().casefold()
                if key in expected_keys and key not in keep_by_key:
                    keep_by_key[key] = row
                else:
                    delete_ids.append(row.id)

            if delete_ids:
                # Parameter rows have no business meaning outside their rule;
                # deleting stale rows directly is safe and avoids stale ORM
                # caches from legacy versions of the mapper.
                self.env.cr.execute(
                    "DELETE FROM wati_automation_parameter WHERE id = ANY(%s)",
                    (delete_ids,),
                )
                Parameter.invalidate_model()

            for index, name in enumerate(expected, start=1):
                key = name.casefold()
                row = keep_by_key.get(key)
                vals = {"param_name": name, "sequence": index * 10}
                if row:
                    row.invalidate_recordset()
                    row.write(vals)
                else:
                    Parameter.create({
                        "rule_id": rule.id,
                        "param_name": name,
                        "sequence": index * 10,
                        "source_type": "field",
                    })

            Parameter.flush_model()
            rule.invalidate_recordset(["parameter_ids"])
            after_rows = Parameter.search([("rule_id", "=", rule.id)], order="sequence, id")
            after_names = after_rows.mapped("param_name")

            _logger.warning(
                "WATI_TEMPLATE_INTEGRITY rule=%s template=%r reason=%s body_tokens=%s before=%s after=%s",
                rule.id,
                rule.template_name,
                reason,
                expected,
                before_names,
                after_names,
            )
        return True

    def action_fetch_template_params(self):
        """Re-sync from the selected template body, never append WATI metadata."""
        self.ensure_one()
        if not self.template_name:
            from odoo.exceptions import UserError

            raise UserError(_("اختر قالب WATI أولًا."))

        self._hard_rebuild_template_parameters(reason="manual_resync")
        mapped = 0
        auto_mapper = getattr(self, "_auto_map_parameters", None)
        if callable(auto_mapper) and self.parameter_ids:
            try:
                mapped = auto_mapper()
            except Exception:
                mapped = 0

        self.invalidate_recordset(["parameter_ids"])
        count = len(self.parameter_ids)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("تمت مزامنة القالب"),
                "message": _(
                    "تم اعتماد نص القالب نفسه كمصدر للمتغيرات: %s متغير. تم اقتراح %s ربط تلقائي.",
                    count,
                    mapped,
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def write(self, vals):
        result = super().write(vals)
        if {"template_name", "template_body", "template_param_names_json"} & set(vals):
            self._hard_rebuild_template_parameters(reason="template_write")
        return result

    @api.model
    def _repair_template_integrity_final(self):
        rules = self.sudo().search([("template_name", "!=", False)], order="id")
        _logger.warning("WATI_TEMPLATE_INTEGRITY_REPAIR_START rules=%s", rules.ids)
        rules._hard_rebuild_template_parameters(reason="module_upgrade")
        _logger.warning("WATI_TEMPLATE_INTEGRITY_REPAIR_DONE rules=%s", rules.ids)
        return True


class WatiAutomationTemplateChoiceIntegrity(models.TransientModel):
    _inherit = "wati.automation.template.choice"

    def action_select(self):
        """Selecting a template is a hard replacement, never an append."""
        self.ensure_one()
        rule = self.rule_id
        body = self.body or ""
        body_names = _tokens_from_body(body)
        cached = _load_param_names(getattr(self, "param_names_json", False))
        canonical = body_names or cached

        rule.write({
            "template_name": self.name,
            "template_body": body or False,
            "template_param_names_json": json.dumps(canonical, ensure_ascii=False),
            "preview_text": False,
            "preview_record_name": False,
        })
        rule._hard_rebuild_template_parameters(reason="template_selection")

        auto_mapper = getattr(rule, "_auto_map_parameters", None)
        if callable(auto_mapper) and rule.parameter_ids:
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
