from odoo import fields, models


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
