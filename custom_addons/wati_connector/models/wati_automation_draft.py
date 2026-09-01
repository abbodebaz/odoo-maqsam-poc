from odoo import fields, models


class WatiAutomationRuleDraft(models.Model):
    _inherit = "wati.automation.rule"

    # The guided wizard validates these fields before moving forward/activation.
    # Keeping drafts permissive lets presets and picker buttons work on a brand-new rule.
    name = fields.Char(string="اسم القاعدة", required=False)
    model_id = fields.Many2one(
        "ir.model",
        string="التطبيق / الموديل",
        required=False,
        ondelete="cascade",
        domain=[("transient", "=", False)],
    )
    trigger_field_id = fields.Many2one(
        "ir.model.fields",
        string="الحقل المراقَب",
        required=False,
        ondelete="cascade",
        domain="[('model_id', '=', model_id), ('store', '=', True)]",
    )
