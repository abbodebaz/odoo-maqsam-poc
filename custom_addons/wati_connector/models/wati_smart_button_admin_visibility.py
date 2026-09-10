from odoo import api, models


class WatiSmartButtonAdminVisibility(models.Model):
    _inherit = "wati.smart.button.location"

    def _generated_arch(self):
        arch = super()._generated_arch()
        return arch.replace(
            'groups="wati_connector.group_wati_agent"',
            'groups="wati_connector.group_wati_agent,base.group_system"',
        )

    @api.model
    def _repair_admin_visibility(self):
        """Regenerate active smart-button views after visibility policy changes."""
        for record in self.sudo().search([("active", "=", True)]):
            record._sync_generated_view()
        return True
