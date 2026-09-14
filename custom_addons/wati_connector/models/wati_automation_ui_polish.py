from odoo import _, fields, models


class WatiAutomationRuleUIPolish(models.Model):
    _inherit = "wati.automation.rule"

    setup_step = fields.Selection(
        selection=[
            ("trigger", "1. Trigger"),
            ("recipient", "2. Recipient"),
            ("message", "3. Message"),
            ("review", "4. Review"),
        ]
    )

    def action_validate_template(self):
        """Verify WATI itself, but do not imply the whole message is ready.

        Template approval and variable mapping are separate checks. A template can
        be live/approved in WATI while the automation still has required
        placeholders with no Odoo value source. In that case keep the template
        verification valid, but return an explicit warning instead of the old
        green success notification.
        """
        self.ensure_one()
        self._validate_template_live(force=True, raise_error=True)

        total = self.template_parameter_count
        mapped = self.template_mapped_count
        mapping_ready = self.template_mapping_state in ("empty", "ready")

        if not mapping_ready:
            missing = max(0, total - mapped)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Template verified — message incomplete"),
                    "message": _(
                        "The WATI template is approved, but the automation message is not ready yet. "
                        "%(mapped)s of %(total)s variables are connected; %(missing)s still need a value source.",
                        mapped=mapped,
                        total=total,
                        missing=missing,
                    ),
                    "type": "warning",
                    "sticky": True,
                    "next": {"type": "ir.actions.client", "tag": "soft_reload"},
                },
            }

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Template verified — message ready"),
                "message": _(
                    "The WATI template is approved and all required template variables are connected."
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }
