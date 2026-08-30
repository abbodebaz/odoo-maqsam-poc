from urllib.parse import quote

import requests

from odoo import _, fields, models
from odoo.exceptions import UserError


class ResUsers(models.Model):
    _inherit = "res.users"

    wati_operator_email = fields.Char(
        string="WATI Operator Email",
        help="إيميل الموظف كما هو مسجل داخل WATI Team Inbox.",
    )

    def _wati_email(self):
        self.ensure_one()
        for value in (self.wati_operator_email, self.email, self.login):
            value = (value or "").strip()
            if "@" in value:
                return value
        return ""


class WatiConversation(models.Model):
    _inherit = "wati.conversation"

    assigned_user_id = fields.Many2one(
        "res.users",
        string="موظف Odoo المسؤول",
        ondelete="set null",
        index=True,
    )
    assigned_at = fields.Datetime(string="وقت الاستلام")

    def assign_to_odoo_user(self, user):
        self.ensure_one()
        user.ensure_one()
        email = user._wati_email()
        if not email:
            raise UserError(_("لا يوجد بريد WATI مرتبط بهذا المستخدم. أضف WATI Operator Email في بطاقة المستخدم."))
        if not self.wa_id:
            raise UserError(_("لا يوجد رقم WhatsApp لهذه المحادثة."))

        params = self.env["ir.config_parameter"].sudo()
        endpoint = (params.get_param("wati_connector.api_endpoint") or "").strip().rstrip("/")
        token = (params.get_param("wati_connector.api_token") or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not endpoint or not token:
            raise UserError(_("إعدادات WATI API غير مكتملة."))

        response = requests.post(
            f"{endpoint}/api/v1/assignOperator",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={"email": email, "whatsappNumber": self.wa_id},
            timeout=20,
        )
        if not response.ok:
            detail = (response.text or response.reason or "").strip()[:500]
            raise UserError(_("WATI رفض تعيين الموظف (%s): %s") % (response.status_code, detail))

        self.write({
            "assigned_user_id": user.id,
            "assigned_at": fields.Datetime.now(),
            "operator_name": user.name,
            "operator_email": email,
        })
        return True
