import secrets

from odoo import api, models


class WatiOtpFlowDefaults(models.Model):
    _inherit = "wati.otp.flow"

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "technical_key" in fields_list and not values.get("technical_key"):
            values["technical_key"] = f"otp_{secrets.token_hex(6)}"
        return values
