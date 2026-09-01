from odoo import _, models


class WatiAutomationRuleBuilder(models.Model):
    _inherit = "wati.automation.rule"

    def action_apply_named_preset(self):
        self.ensure_one()
        preset_key = (self.env.context.get("wati_preset_key") or "").strip()
        if not preset_key:
            return self.action_apply_preset()
        self.preset_key = preset_key
        return self.action_apply_preset()

    def action_start_custom_builder(self):
        self.ensure_one()
        self.write({"preset_key": False, "setup_step": "trigger"})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("إعداد مخصص"),
                "message": _("ابدأ باختيار التطبيق والحقل والقيمة التي تريد مراقبتها."),
                "type": "info",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }
