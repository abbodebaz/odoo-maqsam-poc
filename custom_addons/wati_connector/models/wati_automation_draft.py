from odoo import fields, models


class WatiAutomationRuleDraft(models.Model):
    _inherit = "wati.automation.rule"

    # The guided wizard validates these fields before moving forward/activation.
    # Keeping drafts permissive lets presets and picker buttons work on a brand-new rule.
    name = fields.Char(string="Rule name", required=False)
    model_id = fields.Many2one(
        "ir.model",
        string="Application / Model",
        required=False,
        ondelete="cascade",
        domain=[("transient", "=", False)],
    )
    trigger_field_id = fields.Many2one(
        "ir.model.fields",
        string="Monitored field",
        required=False,
        ondelete="cascade",
        domain="[('model_id', '=', model_id), ('store', '=', True)]",
    )
