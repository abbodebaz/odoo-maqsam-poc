import json
from urllib.parse import quote

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class WatiConversation(models.Model):
    _name = "wati.conversation"
    _description = "WATI WhatsApp Conversation"
    _order = "last_message_at desc, id desc"

    name = fields.Char(string="العميل", required=True, default="WhatsApp")
    conversation_uid = fields.Char(string="Conversation ID", index=True)
    ticket_uid = fields.Char(string="WATI Ticket ID", index=True)
    wa_id = fields.Char(string="WhatsApp ID", index=True)
    bsuid = fields.Char(string="BSUID", index=True)
    sender_name = fields.Char(string="اسم المرسل")
    operator_name = fields.Char(string="الموظف في WATI")
    operator_email = fields.Char(string="بريد الموظف")
    status = fields.Char(string="الحالة")
    last_message = fields.Text(string="آخر رسالة")
    last_message_at = fields.Datetime(string="آخر نشاط", default=fields.Datetime.now, index=True)
    unread_count = fields.Integer(string="غير مقروء", default=0)
    partner_id = fields.Many2one("res.partner", string="عميل Odoo", ondelete="set null", index=True)
    message_ids = fields.One2many("wati.message", "conversation_id", string="الرسائل")

    def action_open_reply_wizard(self):
        self.ensure_one()
        if not self.wa_id:
            raise UserError(_("لا يوجد WhatsApp ID لهذه المحادثة."))
        return {
            "type": "ir.actions.act_window",
            "name": _("رد عبر WhatsApp"),
            "res_model": "wati.reply.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_conversation_id": self.id},
        }


class WatiReplyWizard(models.TransientModel):
    _name = "wati.reply.wizard"
    _description = "WATI WhatsApp Reply"

    conversation_id = fields.Many2one(
        "wati.conversation",
        string="المحادثة",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    wa_id = fields.Char(
        string="رقم WhatsApp",
        related="conversation_id.wa_id",
        readonly=True,
    )
    message = fields.Text(string="الرسالة", required=True)

    def action_send(self):
        self.ensure_one()
        conversation = self.conversation_id
        target = (conversation.wa_id or "").strip()
        text = (self.message or "").strip()
        if not target:
            raise UserError(_("لا يوجد رقم WhatsApp لهذه المحادثة."))
        if not text:
            raise UserError(_("اكتب الرسالة أولًا."))
        if len(text) > 4096:
            raise UserError(_("الرسالة أطول من الحد المسموح في WhatsApp (4096 حرفًا)."))

        params = self.env["ir.config_parameter"].sudo()
        endpoint = (params.get_param("wati_connector.api_endpoint") or "").strip().rstrip("/")
        token = (params.get_param("wati_connector.api_token") or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not endpoint or not token:
            raise UserError(_("إعدادات WATI API غير مكتملة. راجع Settings → WATI WhatsApp."))

        url = f"{endpoint}/api/v1/sendSessionMessage/{quote(target, safe='')}"
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                params={"messageText": text},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise UserError(_("تعذر إرسال رسالة WhatsApp: %s") % exc) from exc

        if not response.ok:
            detail = (response.text or response.reason or "").strip()[:500]
            if response.status_code in (400, 409) and "session" in detail.lower():
                raise UserError(_("لا يمكن إرسال رسالة عادية لأن جلسة WhatsApp غير مفتوحة. سنستخدم Template لهذه الحالة لاحقًا.\n\n%s") % detail)
            raise UserError(_("WATI رفض إرسال الرسالة (%s): %s") % (response.status_code, detail))

        # The authoritative outbound message/status arrives back through WATI webhook.
        # Only clear the local unread counter immediately for agent UX.
        conversation.write({"unread_count": 0})

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WhatsApp"),
                "message": _("تم إرسال الرسالة إلى WATI ✅"),
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
    conversation_id = fields.Many2one("wati.conversation", string="المحادثة", ondelete="cascade", index=True)
    conversation_uid = fields.Char(string="Conversation ID", index=True)
    ticket_uid = fields.Char(string="WATI Ticket ID", index=True)
    wa_id = fields.Char(string="WhatsApp ID", index=True)
    sender_name = fields.Char(string="المرسل")
    direction = fields.Selection(
        [("inbound", "وارد"), ("outbound", "صادر")],
        string="الاتجاه",
        default="inbound",
        index=True,
    )
    message_type = fields.Char(string="نوع الرسالة")
    text = fields.Text(string="النص")
    status = fields.Char(string="حالة الرسالة", index=True)
    operator_name = fields.Char(string="الموظف")
    operator_email = fields.Char(string="بريد الموظف")
    received_at = fields.Datetime(string="وقت الاستقبال", default=fields.Datetime.now, index=True)
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
    received_at = fields.Datetime(string="Received At", default=fields.Datetime.now, index=True)
    payload = fields.Text(string="Payload", required=True)

    @api.model
    def ingest(self, payload):
        if not isinstance(payload, dict):
            return False

        external_id = str(payload.get("id") or payload.get("whatsappMessageId") or "").strip()
        event_type = str(payload.get("eventType") or payload.get("type") or "event").strip()
        wa_id = str(payload.get("waId") or "").strip()
        conversation_uid = str(payload.get("conversationId") or "").strip()
        status = str(payload.get("statusString") or payload.get("status") or "").strip()

        duplicate = False
        if external_id:
            duplicate = bool(self.sudo().search_count([
                ("external_id", "=", external_id),
                ("event_type", "=", event_type),
                ("status", "=", status),
            ], limit=1))
        if not duplicate:
            self.sudo().create({
                "event_type": event_type,
                "external_id": external_id,
                "wa_id": wa_id,
                "conversation_uid": conversation_uid,
                "status": status,
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
            })

        message_id = external_id
        if not message_id:
            return True

        message_model = self.env["wati.message"].sudo()
        existing = message_model.search([("name", "=", message_id)], limit=1)

        if existing:
            values = {}
            if status:
                values["status"] = status
            if payload.get("operatorName"):
                values["operator_name"] = payload.get("operatorName")
            if payload.get("operatorEmail"):
                values["operator_email"] = payload.get("operatorEmail")
            if values:
                existing.write(values)
            return True

        if not (conversation_uid or wa_id or payload.get("text") is not None):
            return True

        conversation_model = self.env["wati.conversation"].sudo()
        conversation = False
        if conversation_uid:
            conversation = conversation_model.search([("conversation_uid", "=", conversation_uid)], limit=1)
        if not conversation and wa_id:
            conversation = conversation_model.search([("wa_id", "=", wa_id)], limit=1)

        sender_name = str(payload.get("senderName") or wa_id or "WhatsApp").strip()
        text = payload.get("text") or ""
        if not conversation:
            conversation = conversation_model.create({
                "name": sender_name,
                "conversation_uid": conversation_uid,
                "ticket_uid": str(payload.get("ticketId") or "").strip(),
                "wa_id": wa_id,
                "bsuid": str(payload.get("bsuid") or "").strip(),
                "sender_name": sender_name,
                "operator_name": payload.get("operatorName") or "",
                "operator_email": payload.get("operatorEmail") or "",
                "status": status,
                "last_message": text,
                "last_message_at": fields.Datetime.now(),
                "unread_count": 0 if payload.get("owner") else 1,
            })
        else:
            conversation.write({
                "ticket_uid": str(payload.get("ticketId") or conversation.ticket_uid or "").strip(),
                "sender_name": sender_name or conversation.sender_name,
                "operator_name": payload.get("operatorName") or conversation.operator_name,
                "operator_email": payload.get("operatorEmail") or conversation.operator_email,
                "status": status or conversation.status,
                "last_message": text or conversation.last_message,
                "last_message_at": fields.Datetime.now(),
                "unread_count": conversation.unread_count + (0 if payload.get("owner") else 1),
            })

        message_model.create({
            "name": message_id,
            "whatsapp_message_id": str(payload.get("whatsappMessageId") or "").strip(),
            "conversation_id": conversation.id,
            "conversation_uid": conversation_uid,
            "ticket_uid": str(payload.get("ticketId") or "").strip(),
            "wa_id": wa_id,
            "sender_name": sender_name,
            "direction": "outbound" if payload.get("owner") else "inbound",
            "message_type": str(payload.get("type") or "text"),
            "text": text,
            "status": status,
            "operator_name": payload.get("operatorName") or "",
            "operator_email": payload.get("operatorEmail") or "",
            "raw_payload": json.dumps(payload, ensure_ascii=False, default=str),
        })
        return True
