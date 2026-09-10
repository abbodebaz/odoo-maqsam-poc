import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_MESSAGE_STATUS_RANK = {
    "accepted": 0,
    "queued": 0,
    "pending": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
    "replied": 4,
}
_FAILED_STATUS_TOKENS = ("fail", "error", "undeliver", "reject", "expired")


def _clean_text(value):
    if value in (None, False):
        return ""
    return str(value).strip()


def _payload_event_id(payload):
    """Return the identity of a webhook event, not the message itself."""
    for key in ("id", "localMessageId", "whatsappMessageId"):
        value = _clean_text(payload.get(key))
        if value:
            return value
    return ""


def _payload_message_identity(payload):
    """Return a stable identity for a WhatsApp message across callbacks."""
    for key in ("whatsappMessageId", "localMessageId", "id"):
        value = _clean_text(payload.get(key))
        if value:
            return value
    return ""


def _payload_owner(payload):
    value = payload.get("owner")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y"}
    return False


def _payload_direction(payload):
    if _payload_owner(payload):
        return "outbound"
    event_type = _clean_text(payload.get("eventType") or payload.get("type")).casefold()
    outbound_markers = (
        "sessionmessagesent",
        "templatemessagesent",
        "sentmessage",
        "outbound",
    )
    return "outbound" if any(marker in event_type for marker in outbound_markers) else "inbound"


def _status_rank(value):
    clean = _clean_text(value).casefold()
    for token, rank in _MESSAGE_STATUS_RANK.items():
        if token in clean:
            return rank
    return -1


def _is_failed_status(value):
    clean = _clean_text(value).casefold()
    return any(token in clean for token in _FAILED_STATUS_TOKENS)


def _advance_message_status(current, incoming):
    """Keep lifecycle monotonic and resilient to out-of-order callbacks."""
    current = _clean_text(current)
    incoming = _clean_text(incoming)
    if not incoming:
        return current
    if not current:
        return incoming

    current_rank = _status_rank(current)
    incoming_rank = _status_rank(incoming)
    current_failed = _is_failed_status(current)
    incoming_failed = _is_failed_status(incoming)

    if incoming_failed and current_rank >= 2:
        return current
    if current_failed and incoming_rank >= 0:
        return incoming
    if incoming_failed:
        return incoming
    if incoming_rank >= current_rank:
        return incoming
    return current


def _status_time_field(status):
    clean = _clean_text(status).casefold()
    if "replied" in clean or "read" in clean:
        return "read_at"
    if "deliver" in clean:
        return "delivered_at"
    if "sent" in clean:
        return "sent_at"
    if _is_failed_status(clean):
        return "failed_at"
    if any(token in clean for token in ("accepted", "queued", "pending")):
        return "accepted_at"
    return ""


class WatiConversation(models.Model):
    _name = "wati.conversation"
    _description = "WATI WhatsApp Conversation"
    _order = "last_message_at desc, id desc"

    name = fields.Char(string="Customer", required=True, default="WhatsApp")
    conversation_uid = fields.Char(string="Conversation ID", index=True)
    ticket_uid = fields.Char(string="WATI Ticket ID", index=True)
    wa_id = fields.Char(string="WhatsApp ID", index=True)
    bsuid = fields.Char(string="BSUID", index=True)
    sender_name = fields.Char(string="Sender’s name")
    operator_name = fields.Char(string="employee in WATI")
    operator_email = fields.Char(string="Employee email")
    status = fields.Char(string="Status")
    last_message = fields.Text(string="Last message")
    last_message_at = fields.Datetime(
        string="Latest activity", default=fields.Datetime.now, index=True
    )
    unread_count = fields.Integer(string="Unreadable", default=0)
    partner_id = fields.Many2one(
        "res.partner", string="Client Odoo", ondelete="set null", index=True
    )
    message_ids = fields.One2many(
        "wati.message", "conversation_id", string="Messages"
    )

    def action_open_reply_wizard(self):
        self.ensure_one()
        if not self.wa_id:
            raise UserError(_("There is no WhatsApp ID for this conversation."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Reply via WhatsApp"),
            "res_model": "wati.reply.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_conversation_id": self.id},
        }

    def send_session_message(self, text):
        """Public text-send entry point; transport lives in the service layer."""
        self.ensure_one()
        return self._wati_send_text_via_client(text)


class WatiReplyWizard(models.TransientModel):
    _name = "wati.reply.wizard"
    _description = "WATI WhatsApp Reply"

    conversation_id = fields.Many2one(
        "wati.conversation",
        string="Conversation",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    wa_id = fields.Char(
        string="No WhatsApp",
        related="conversation_id.wa_id",
        readonly=True,
    )
    message = fields.Text(string="The message", required=True)

    def action_send(self):
        self.ensure_one()
        self.conversation_id.send_session_message(self.message)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WhatsApp"),
                "message": _("The message has been accepted WATI ✅"),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }


class WatiMessage(models.Model):
    _name = "wati.message"
    _description = "WATI WhatsApp Message"
    _order = "received_at desc, id desc"

    name = fields.Char(string="Message ID", required=True, index=True)
    whatsapp_message_id = fields.Char(string="WhatsApp Message ID", index=True)
    local_message_id = fields.Char(string="Local Message ID", index=True)
    conversation_id = fields.Many2one(
        "wati.conversation", string="Conversation", ondelete="cascade", index=True
    )
    conversation_uid = fields.Char(string="Conversation ID", index=True)
    ticket_uid = fields.Char(string="WATI Ticket ID", index=True)
    wa_id = fields.Char(string="WhatsApp ID", index=True)
    bsuid = fields.Char(string="BSUID", index=True)
    channel_phone_number = fields.Char(string="channel WhatsApp", index=True)
    sender_name = fields.Char(string="Sender")
    direction = fields.Selection(
        [("inbound", "Incoming"), ("outbound", "Outgoing")],
        string="direction",
        default="inbound",
        index=True,
    )
    message_type = fields.Char(string="Message type")
    text = fields.Text(string="Text")
    status = fields.Char(string="Message status", index=True)
    operator_name = fields.Char(string="Employee")
    operator_email = fields.Char(string="Employee email")
    received_at = fields.Datetime(
        string="Reception time", default=fields.Datetime.now, index=True
    )
    accepted_at = fields.Datetime(string="Acceptance time", readonly=True)
    sent_at = fields.Datetime(string="Transmission time", readonly=True)
    delivered_at = fields.Datetime(string="Delivery time", readonly=True)
    read_at = fields.Datetime(string="Reading time", readonly=True)
    failed_at = fields.Datetime(string="Failure time", readonly=True)
    status_updated_at = fields.Datetime(
        string="Latest status update", readonly=True, index=True
    )
    raw_payload = fields.Text(string="Raw Payload")


class WatiWebhookEvent(models.Model):
    _name = "wati.webhook.event"
    _description = "WATI Webhook Event"
    _order = "received_at desc, id desc"

    event_type = fields.Char(string="Event Type", index=True)
    external_id = fields.Char(string="External ID", index=True)
    wa_id = fields.Char(string="WhatsApp ID", index=True)
    conversation_uid = fields.Char(string="Conversation ID", index=True)
    status = fields.Char(string="Status")
    received_at = fields.Datetime(
        string="Received At", default=fields.Datetime.now, index=True
    )
    payload = fields.Text(string="Payload", required=True)

    @api.model
    def ingest(self, payload):
        if not isinstance(payload, dict):
            return False

        event_external_id = _payload_event_id(payload)
        message_identity = _payload_message_identity(payload)
        whatsapp_message_id = _clean_text(payload.get("whatsappMessageId"))
        local_message_id = _clean_text(payload.get("localMessageId"))
        event_type = _clean_text(payload.get("eventType") or payload.get("type") or "event")
        wa_id = _clean_text(payload.get("waId"))
        conversation_uid = _clean_text(payload.get("conversationId"))
        status = _clean_text(payload.get("statusString") or payload.get("status"))
        direction = _payload_direction(payload)
        now = fields.Datetime.now()

        duplicate = False
        if event_external_id:
            duplicate = bool(
                self.sudo().search_count(
                    [
                        ("external_id", "=", event_external_id),
                        ("event_type", "=", event_type),
                        ("status", "=", status),
                    ],
                    limit=1,
                )
            )
        if not duplicate:
            self.sudo().create(
                {
                    "event_type": event_type,
                    "external_id": event_external_id,
                    "wa_id": wa_id,
                    "conversation_uid": conversation_uid,
                    "status": status,
                    "payload": json.dumps(payload, ensure_ascii=False, default=str),
                }
            )

        if not message_identity:
            return True

        message_model = self.env["wati.message"].sudo()
        existing = message_model.browse()
        if whatsapp_message_id:
            existing = message_model.search(
                [("whatsapp_message_id", "=", whatsapp_message_id)],
                order="id desc",
                limit=1,
            )
        if not existing and local_message_id:
            existing = message_model.search(
                [("local_message_id", "=", local_message_id)],
                order="id desc",
                limit=1,
            )
        if not existing:
            existing = message_model.search(
                [("name", "=", message_identity)], order="id desc", limit=1
            )

        if existing:
            values = {
                "status_updated_at": now,
                "raw_payload": json.dumps(payload, ensure_ascii=False, default=str),
            }
            next_status = _advance_message_status(existing.status, status)
            if next_status and next_status != existing.status:
                values["status"] = next_status
                time_field = _status_time_field(next_status)
                if time_field and not existing[time_field]:
                    values[time_field] = now
            if whatsapp_message_id and not existing.whatsapp_message_id:
                values["whatsapp_message_id"] = whatsapp_message_id
            if local_message_id and not existing.local_message_id:
                values["local_message_id"] = local_message_id
            if conversation_uid and not existing.conversation_uid:
                values["conversation_uid"] = conversation_uid
            if wa_id and not existing.wa_id:
                values["wa_id"] = wa_id
            if payload.get("bsuid") and not existing.bsuid:
                values["bsuid"] = _clean_text(payload.get("bsuid"))
            if payload.get("channelPhoneNumber") and not existing.channel_phone_number:
                values["channel_phone_number"] = _clean_text(payload.get("channelPhoneNumber"))
            if payload.get("operatorName"):
                values["operator_name"] = payload.get("operatorName")
            if payload.get("operatorEmail"):
                values["operator_email"] = payload.get("operatorEmail")
            existing.write(values)
            return True

        if not (conversation_uid or wa_id or payload.get("text") is not None):
            return True

        conversation_model = self.env["wati.conversation"].sudo()
        conversation = conversation_model.browse()
        if conversation_uid:
            conversation = conversation_model.search(
                [("conversation_uid", "=", conversation_uid)],
                order="id desc",
                limit=1,
            )
        if not conversation and wa_id:
            conversation = conversation_model.search(
                [("wa_id", "=", wa_id)], order="id desc", limit=1
            )

        sender_name = _clean_text(payload.get("senderName")) or wa_id or "WhatsApp"
        text = payload.get("text") or ""
        bsuid = _clean_text(payload.get("bsuid"))
        channel_phone_number = _clean_text(payload.get("channelPhoneNumber"))

        if not conversation:
            conversation = conversation_model.create(
                {
                    "name": sender_name,
                    "conversation_uid": conversation_uid,
                    "ticket_uid": _clean_text(payload.get("ticketId")),
                    "wa_id": wa_id,
                    "bsuid": bsuid,
                    "sender_name": sender_name,
                    "operator_name": payload.get("operatorName") or "",
                    "operator_email": payload.get("operatorEmail") or "",
                    "status": status,
                    "last_message": text,
                    "last_message_at": now,
                    "unread_count": 0 if direction == "outbound" else 1,
                }
            )
        else:
            conversation_values = {
                "ticket_uid": _clean_text(payload.get("ticketId"))
                or conversation.ticket_uid,
                "status": status or conversation.status,
                "last_message": text or conversation.last_message,
                "last_message_at": now,
                "unread_count": conversation.unread_count
                + (0 if direction == "outbound" else 1),
            }
            if wa_id and not conversation.wa_id:
                conversation_values["wa_id"] = wa_id
            if bsuid and not conversation.bsuid:
                conversation_values["bsuid"] = bsuid
            if direction == "inbound" and payload.get("senderName"):
                conversation_values["sender_name"] = sender_name
                if not conversation.partner_id:
                    conversation_values["name"] = sender_name
            if payload.get("operatorName"):
                conversation_values["operator_name"] = payload.get("operatorName")
            if payload.get("operatorEmail"):
                conversation_values["operator_email"] = payload.get("operatorEmail")
            conversation.write(conversation_values)

        message_values = {
            "name": message_identity,
            "whatsapp_message_id": whatsapp_message_id,
            "local_message_id": local_message_id,
            "conversation_id": conversation.id,
            "conversation_uid": conversation_uid,
            "ticket_uid": _clean_text(payload.get("ticketId")),
            "wa_id": wa_id,
            "bsuid": bsuid,
            "channel_phone_number": channel_phone_number,
            "sender_name": sender_name,
            "direction": direction,
            "message_type": _clean_text(payload.get("type")) or "text",
            "text": text,
            "status": status,
            "operator_name": payload.get("operatorName") or "",
            "operator_email": payload.get("operatorEmail") or "",
            "received_at": now,
            "status_updated_at": now,
            "raw_payload": json.dumps(payload, ensure_ascii=False, default=str),
        }
        time_field = _status_time_field(status)
        if time_field:
            message_values[time_field] = now
        message_model.create(message_values)
        return True
