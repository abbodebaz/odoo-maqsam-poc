from odoo import api, fields, models


class WatiSupportTicket(models.Model):
    _name = "wati.support.ticket"
    _description = "WhatsApp Customer Service Ticket"
    _order = "create_date desc, id desc"

    name = fields.Char(string="Ticket number", required=True, copy=False, default="New", index=True)
    subject = fields.Char(string="Topic", required=True)
    partner_id = fields.Many2one("res.partner", string="Customer", ondelete="set null", index=True)
    conversation_id = fields.Many2one(
        "wati.conversation",
        string="Conversation WhatsApp",
        ondelete="set null",
        index=True,
    )
    wa_id = fields.Char(string="No WhatsApp", related="conversation_id.wa_id", store=True, readonly=True)
    user_id = fields.Many2one(
        "res.users",
        string="Responsible employee",
        default=lambda self: self.env.user,
        ondelete="set null",
        index=True,
    )
    status = fields.Selection(
        [
            ("new", "New"),
            ("in_progress", "In process"),
            ("waiting", "Waiting for the customer"),
            ("done", "Closed"),
            ("cancelled", "Canceled"),
        ],
        string="Status",
        default="new",
        required=True,
        index=True,
    )
    priority = fields.Selection(
        [("0", "Normal"), ("1", "Mission"), ("2", "Urgent")],
        string="Priority",
        default="0",
        required=True,
    )
    description = fields.Text(string="Details")

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == "New":
                vals["name"] = sequence.next_by_code("wati.support.ticket") or "New"
        return super().create(vals_list)
