from odoo import _, fields, models
from odoo.exceptions import UserError

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError


class ResUsers(models.Model):
    _inherit = "res.users"

    wati_operator_email = fields.Char(
        string="WATI Operator Email",
        help="Employee email as registered inside WATI Team Inbox.",
    )

    def _wati_email(self):
        """Never silently identify a WATI agent using the Odoo login or email."""
        self.ensure_one()
        return (self.wati_operator_email or "").strip()

    def _wati_require_operator_email(self):
        self.ensure_one()
        email = self._wati_email()
        if not email:
            raise UserError(_(
                "Your WATI Agent account is not linked. Ask an administrator to set "
                "WATI Operator Email on your Odoo user before assigning or sending messages."
            ))
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise UserError(_(
                "WATI Operator Email is invalid. Ask an administrator to enter the email "
                "registered for your Agent account in WATI."
            ))
        return email

    def _wati_can_supervise(self):
        self.ensure_one()
        return bool(
            self.has_group("wati_connector.group_wati_supervisor")
            or self.has_group("base.group_system")
        )


class WatiConversation(models.Model):
    _inherit = "wati.conversation"

    assigned_user_id = fields.Many2one(
        "res.users",
        string="Agent Odoo Administrator",
        ondelete="set null",
        index=True,
    )
    assigned_at = fields.Datetime(string="Pick up time")

    def _lock_assignment_row(self):
        """Serialize assignment changes for this conversation."""
        self.ensure_one()
        self.flush_recordset(["assigned_user_id"])
        self.env.cr.execute(
            "SELECT id FROM wati_conversation WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset(
            ["assigned_user_id", "assigned_at", "operator_name", "operator_email"]
        )

    def assign_to_odoo_user(self, user, force=False):
        self.ensure_one()
        user.ensure_one()
        self._lock_assignment_row()

        previous_user = self.assigned_user_id
        actor = self.env.user
        if previous_user and previous_user != user:
            if not force:
                raise UserError(_("This conversation was received by %s.") % previous_user.name)
            if not actor._wati_can_supervise():
                raise UserError(
                    _(
                        "You do not have the authority to transfer a conversation received by another employee. "
                        "Ask a supervisor WATI Transfer execution."
                    )
                )

        email = user._wati_require_operator_email()
        if not self.wa_id:
            raise UserError(_("There is no number WhatsApp for this conversation."))

        try:
            response = WatiClient(self.env).assign_operator(self.wa_id, email)
            # WATI can return an application-level rejection inside HTTP 200.
            WatiClient(self.env)._ensure_application_success(response, "operator assignment")
        except WatiConfigurationError as exc:
            raise UserError(_("Settings WATI API Incomplete.")) from exc
        except WatiRequestError as exc:
            detail = (exc.response_text or str(exc) or "").strip()[:500]
            if exc.status_code:
                raise UserError(
                    _("WATI Refusal to hire an employee (%s): %s") % (exc.status_code, detail)
                ) from exc
            raise UserError(_("Unable to contact WATI To appoint the employee: %s") % detail) from exc

        now = fields.Datetime.now()
        self.write(
            {
                "assigned_user_id": user.id,
                "assigned_at": now,
                "operator_name": user.name,
                "operator_email": email,
            }
        )

        if previous_user != user:
            self.env["wati.assignment.log"].sudo().create(
                {
                    "conversation_id": self.id,
                    "from_user_id": previous_user.id if previous_user else False,
                    "to_user_id": user.id,
                    "moved_by_user_id": actor.id,
                    "moved_at": now,
                }
            )
        return True

    def send_session_message(self, text):
        self.ensure_one()
        current_user = self.env.user
        current_user._wati_require_operator_email()
        if not self.assigned_user_id:
            self.assign_to_odoo_user(current_user)
        elif self.assigned_user_id != current_user:
            raise UserError(
                _(
                    "This conversation was received by %s. "
                    "It must be transferred to you first before sending."
                )
                % self.assigned_user_id.name
            )
        return self._wati_send_text_via_client(text)


class WatiAssignmentLog(models.Model):
    _name = "wati.assignment.log"
    _description = "WATI Conversation Assignment History"
    _order = "moved_at desc, id desc"

    conversation_id = fields.Many2one(
        "wati.conversation", required=True, ondelete="cascade", index=True
    )
    from_user_id = fields.Many2one(
        "res.users", string="From the employee", ondelete="set null"
    )
    to_user_id = fields.Many2one(
        "res.users", string="To the employee", required=True, ondelete="restrict"
    )
    moved_by_user_id = fields.Many2one(
        "res.users", string="Carry out the transfer", required=True, ondelete="restrict"
    )
    moved_at = fields.Datetime(
        string="Transportation time", required=True, default=fields.Datetime.now, index=True
    )
