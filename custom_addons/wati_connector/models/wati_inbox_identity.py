"""Identity gate for interactive inboxes only; OTP/automations remain unaffected."""
import re

from odoo import _, fields, models
from odoo.exceptions import UserError


class ResUsers(models.Model):
    _inherit = "res.users"

    wati_approved_operator_email = fields.Char(
        string="Approved WATI Agent Email",
        help="An Odoo administrator must check this email against the Agent in WATI before approving it. Changing WATI Operator Email immediately invalidates the approval.",
        groups="base.group_system",
        copy=False,
    )

    def _wati_inbox_identity_error(self):
        """Never mistake a colleague's conversation ownership for this user's identity."""
        self.ensure_one()
        email = self._wati_email().casefold()
        if not email:
            return _("WhatsApp inbox is locked: your WATI Agent email is missing. Ask an administrator to link and approve your account.")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return _("WhatsApp inbox is locked: the WATI Agent email is not a valid email address. Ask an administrator to correct it.")

        approved = (self.sudo().wati_approved_operator_email or "").strip().casefold()
        if approved:
            if approved != email:
                return _("WhatsApp inbox is locked: your WATI Agent email differs from the approved account. Ask an administrator to restore or reapprove the correct email.")
            return False

        # Compatibility for existing employees only: a conversation already
        # assigned to THIS Odoo user with the SAME WATI email is evidence of a
        # prior accepted assignment. Never inspect another employee's ownership.
        own = self.env["wati.conversation"].sudo().search(
            [("assigned_user_id", "=", self.id)],
            order="assigned_at desc, id desc",
            limit=1,
        )
        if own and (own.operator_email or "").strip().casefold() == email:
            return False
        if own:
            return _("WhatsApp inbox is locked: your WATI Agent email does not match your previously assigned WATI identity. Ask an administrator to verify the account and approve its email.")
        return _("WhatsApp inbox is locked: this WATI Agent email has not been approved. Ask an administrator to verify the Agent in WATI and set Approved WATI Agent Email on your Odoo user.")

    def _wati_require_inbox_identity(self):
        self.ensure_one()
        error = self._wati_inbox_identity_error()
        if error:
            raise UserError(error)
        return self._wati_email()


class WatiConversation(models.Model):
    _inherit = "wati.conversation"

    def _wati_require_manual_sender(self):
        self.env.user._wati_require_inbox_identity()
        return super()._wati_require_manual_sender()

    def assign_to_odoo_user(self, user, force=False):
        user._wati_require_inbox_identity()
        return super().assign_to_odoo_user(user, force=force)
