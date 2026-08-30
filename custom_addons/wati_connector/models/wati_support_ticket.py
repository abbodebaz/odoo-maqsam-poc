from odoo import api, fields, models


class WatiSupportTicket(models.Model):
    _name = "wati.support.ticket"
    _description = "WhatsApp Customer Service Ticket"
    _order = "create_date desc, id desc"

    name = fields.Char(string="رقم التذكرة", required=True, copy=False, default="جديد", index=True)
    subject = fields.Char(string="الموضوع", required=True)
    partner_id = fields.Many2one("res.partner", string="العميل", ondelete="set null", index=True)
    conversation_id = fields.Many2one(
        "wati.conversation",
        string="محادثة WhatsApp",
        ondelete="set null",
        index=True,
    )
    wa_id = fields.Char(string="رقم WhatsApp", related="conversation_id.wa_id", store=True, readonly=True)
    user_id = fields.Many2one(
        "res.users",
        string="الموظف المسؤول",
        default=lambda self: self.env.user,
        ondelete="set null",
        index=True,
    )
    status = fields.Selection(
        [
            ("new", "جديدة"),
            ("in_progress", "قيد المعالجة"),
            ("waiting", "بانتظار العميل"),
            ("done", "مغلقة"),
            ("cancelled", "ملغاة"),
        ],
        string="الحالة",
        default="new",
        required=True,
        index=True,
    )
    priority = fields.Selection(
        [("0", "عادية"), ("1", "مهمة"), ("2", "عاجلة")],
        string="الأولوية",
        default="0",
        required=True,
    )
    description = fields.Text(string="التفاصيل")

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == "جديد":
                vals["name"] = sequence.next_by_code("wati.support.ticket") or "جديد"
        return super().create(vals_list)
