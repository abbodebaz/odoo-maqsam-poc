from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    maqsam_agent_email = fields.Char(
        string="Maqsam Agent Email",
        help="إيميل الموظف كما هو مسجل في Maqsam. إذا تركته فارغًا سيستخدم Odoo البريد أو اسم الدخول.",
    )
