import json
import uuid

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..services.client import WatiClient
from ..services.exceptions import WatiConfigurationError, WatiRequestError


class WatiConversationTransport(models.Model):
    _inherit = "wati.conversation"

    def _wati_send_text_via_client(self, text):
        """Send one session message through the centralized WATI transport.

        Assignment/authorization remains the responsibility of the public
        ``send_session_message`` method. This helper owns only transport and the
        immediate local Accepted record used for webhook correlation.
        """
        self.ensure_one()
        target = (self.wa_id or "").strip()
        text = (text or "").strip()
        if not target:
            raise UserError(_("There is no number WhatsApp for this conversation."))
        if not text:
            raise UserError(_("Write the message first."))
        if len(text) > 4096:
            raise UserError(_("The message is longer than the allowed limit WhatsApp (4096 A letter)."))

        client = WatiClient(self.env)
        local_message_id = str(uuid.uuid4())
        channel_number = client.config.channel_number

        try:
            response = client.send_session_message(
                target,
                text,
                local_message_id=local_message_id,
                channel_number=channel_number,
            )
        except WatiConfigurationError as exc:
            raise UserError(_("Settings WATI API Incomplete. See Settings → WATI WhatsApp.")) from exc
        except WatiRequestError as exc:
            detail = (exc.response_text or str(exc) or "").strip()[:800]
            if exc.status_code in (400, 409) and "session" in detail.lower():
                raise UserError(
                    _(
                        "A regular message cannot be sent because it is a session WhatsApp Not open. "
                        "Use Template Approved to start the conversation.\n\n%s"
                    )
                    % detail
                ) from exc
            if exc.status_code:
                raise UserError(_("WATI Refused to send the message (%s): %s") % (exc.status_code, detail)) from exc
            raise UserError(_("Unable to send a message WhatsApp: %s") % detail) from exc

        now = fields.Datetime.now()
        Message = self.env["wati.message"].sudo()
        pending = Message.search([("local_message_id", "=", local_message_id)], limit=1)
        if not pending:
            Message.create(
                {
                    "name": local_message_id,
                    "local_message_id": local_message_id,
                    "conversation_id": self.id,
                    "conversation_uid": self.conversation_uid or "",
                    "ticket_uid": self.ticket_uid or "",
                    "wa_id": target,
                    "bsuid": self.bsuid or "",
                    "sender_name": self.env.user.name or "Odoo",
                    "direction": "outbound",
                    "message_type": "text",
                    "text": text,
                    "status": "Accepted",
                    "operator_name": self.env.user.name or "",
                    "operator_email": self.env.user.email or "",
                    "channel_phone_number": channel_number,
                    "received_at": now,
                    "accepted_at": now,
                    "status_updated_at": now,
                    "raw_payload": json.dumps(
                        {
                            "source": "odoo_session_send",
                            "localMessageId": local_message_id,
                            "httpStatus": response.status_code,
                        },
                        ensure_ascii=False,
                    ),
                }
            )

        self.write(
            {
                "last_message": text,
                "last_message_at": now,
                "unread_count": 0,
            }
        )
        return True
