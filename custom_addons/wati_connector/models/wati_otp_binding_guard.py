from odoo import api, models


class WatiOtpVariableBindingGuard(models.Model):
    _inherit = "wati.otp.variable.binding"

    @api.model_create_multi
    def create(self, vals_list):
        """Preserve template variable names created by the flow onchange.

        Odoo can omit readonly one2many values from the create payload even when
        they are visible in the editable list. Reconstruct the variable name
        from the selected template so saving the flow never fails on an
        internal readonly field.
        """
        assigned_by_flow = {}
        for vals in vals_list:
            if vals.get("variable_name"):
                continue

            flow_id = vals.get("flow_id")
            if not flow_id:
                continue

            flow = self.env["wati.otp.flow"].browse(flow_id).exists()
            if not flow or not flow.template_id:
                continue

            variables = flow.template_id.variable_ids.sorted("position")
            if not variables:
                continue

            assigned = assigned_by_flow.setdefault(
                flow.id,
                set(flow.binding_ids.mapped("variable_name")),
            )
            sequence = vals.get("sequence") or 0
            candidate = variables.filtered(
                lambda variable: (variable.position or 0) == sequence
                and variable.name not in assigned
            )[:1]
            if not candidate:
                candidate = variables.filtered(
                    lambda variable: variable.name not in assigned
                )[:1]
            if candidate:
                vals["variable_name"] = candidate.name
                assigned.add(candidate.name)

        return super().create(vals_list)
