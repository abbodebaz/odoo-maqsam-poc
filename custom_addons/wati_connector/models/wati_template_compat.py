from odoo import models


class WatiTemplateOdoo19Compat(models.Model):
    _inherit = "wati.template"

    def action_sync_from_wati(self, *args, **kwargs):
        """Accept list-header RPC arguments added by Odoo 19.

        Odoo 19 may pass the current/selected row ids as an extra positional
        argument when a model button is rendered in a list header. Template
        synchronization is intentionally global, so those ids must not alter
        the operation. Keep the provider/business logic in the canonical
        implementation and only normalize the RPC boundary here.
        """
        return super().action_sync_from_wati()
