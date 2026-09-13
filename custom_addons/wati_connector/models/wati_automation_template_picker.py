import json
import re

from odoo import _, models
from odoo.exceptions import UserError

from .wati_automation_guard import (
    _same_channel,
    _template_category,
    _template_channel,
    _template_language,
    _template_status,
)
from .wati_automation_improvements import _template_body, _template_name
from .wati_automation_template_contract import (
    _APPROVED_STATES,
    _GENERIC_TEMPLATE_NAMES,
    _build_template_contract,
    _template_external_id,
)


class WatiAutomationRuleTemplatePicker(models.Model):
    """Keep template browsing usable before a WATI channel is preselected.

    The selected live template remains the source of truth for its channel.
    A configured/rule channel is only a filter for multi-channel accounts; it
    must never be a prerequisite for opening the WATI template picker.
    """

    _inherit = "wati.automation.rule"

    def action_pick_template(self):
        self.ensure_one()
        effective_channel = self._effective_channel()
        templates = self._fetch_wati_templates_guarded()

        Choice = self.env["wati.automation.template.choice"]
        Choice.search([("rule_id", "=", self.id)]).unlink()

        values = []
        for item in templates:
            name = _template_name(item).strip()
            if not name or name.casefold() in _GENERIC_TEMPLATE_NAMES:
                continue

            status = _template_status(item).strip()
            channel = _template_channel(item).strip()
            if status.casefold() not in _APPROVED_STATES:
                continue
            if effective_channel and channel and not _same_channel(
                channel, effective_channel
            ):
                continue

            contract = _build_template_contract(item)
            values.append(
                {
                    "rule_id": self.id,
                    "name": name,
                    "status": status,
                    "category": _template_category(item),
                    "body": _template_body(item),
                    "language": _template_language(item),
                    "channel_number": channel or effective_channel,
                    "template_external_id": _template_external_id(item),
                    "contract_json": json.dumps(contract, ensure_ascii=False),
                }
            )

        if not values:
            if effective_channel:
                raise UserError(
                    _(
                        "No approved WATI templates were found for channel %(channel)s.",
                        channel=effective_channel,
                    )
                )
            raise UserError(
                _("No approved WATI templates were found in the connected WATI account.")
            )

        unique = {}
        for vals in values:
            key = (
                vals["name"].casefold(),
                (vals["language"] or "").casefold(),
                re.sub(r"\D+", "", vals["channel_number"] or ""),
            )
            unique[key] = vals
        Choice.create(list(unique.values()))

        return {
            "type": "ir.actions.act_window",
            "name": _("Choose an Approved WATI Template"),
            "res_model": "wati.automation.template.choice",
            "view_mode": "list",
            "views": [
                (
                    self.env.ref(
                        "wati_connector.view_wati_automation_template_choice_list"
                    ).id,
                    "list",
                )
            ],
            "domain": [("rule_id", "=", self.id)],
            "target": "new",
        }
