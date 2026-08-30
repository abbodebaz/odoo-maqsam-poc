from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    maqsam_agent_email = fields.Char(
        string="Maqsam Agent Email",
        help="إيميل الموظف كما هو مسجل في Maqsam. إذا تركته فارغًا سيستخدم Odoo البريد أو اسم الدخول.",
    )
    maqsam_supervisor = fields.Boolean(
        string="مشرف Maqsam",
        groups="base.group_system",
        help="يسمح للمستخدم بمشاهدة مكالمات وحالات جميع موظفي Maqsam. الموظف العادي يرى بياناته فقط.",
        default=False,
    )
