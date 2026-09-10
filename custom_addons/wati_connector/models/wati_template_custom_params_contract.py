from odoo import models


class WatiTemplateCustomParamsContract(models.Model):
    """Serialize template sample values using WATI's persisted provider contract.

    Live approved templates returned by WATI expose custom parameters as
    ``paramName``/``paramValue``. Requests sent with the generic
    ``name``/``value`` keys were accepted by the HTTP endpoint but persisted by
    WATI as null values, which leaves Meta without the variable samples it needs
    to review the template reliably.
    """

    _inherit = "wati.template"

    def _build_submission_payload(self):
        self.ensure_one()
        payload = super()._build_submission_payload()
        payload["customParams"] = [
            {
                "paramName": line.name,
                "paramValue": line.sample_value or "",
            }
            for line in self.variable_ids.sorted("position")
        ]
        return payload
