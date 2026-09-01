import re

from odoo import _, fields, models
from odoo.exceptions import UserError


class WatiConversationHelpdesk(models.Model):
    _inherit = "wati.conversation"

    helpdesk_ticket_ids = fields.Many2many(
        "helpdesk.ticket",
        "wati_helpdesk_ticket_conversation_rel",
        "conversation_id",
        "ticket_id",
        string="تذاكر Helpdesk المرتبطة",
        copy=False,
    )
    helpdesk_ticket_count = fields.Integer(
        string="عدد تذاكر Helpdesk",
        compute="_compute_helpdesk_ticket_count",
    )

    def _compute_helpdesk_ticket_count(self):
        for conversation in self:
            conversation.helpdesk_ticket_count = len(conversation.helpdesk_ticket_ids)

    def action_open_helpdesk_tickets(self):
        self.ensure_one()
        if not self.helpdesk_ticket_ids:
            raise UserError(_("لا توجد تذاكر Helpdesk مرتبطة بهذه المحادثة."))
        if len(self.helpdesk_ticket_ids) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": self.helpdesk_ticket_ids.display_name,
                "res_model": "helpdesk.ticket",
                "res_id": self.helpdesk_ticket_ids.id,
                "view_mode": "form",
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("تذاكر Helpdesk"),
            "res_model": "helpdesk.ticket",
            "view_mode": "list,form",
            "domain": [("id", "in", self.helpdesk_ticket_ids.ids)],
            "target": "current",
        }


class HelpdeskTicketWati(models.Model):
    _inherit = "helpdesk.ticket"

    wati_conversation_ids = fields.Many2many(
        "wati.conversation",
        "wati_helpdesk_ticket_conversation_rel",
        "ticket_id",
        "conversation_id",
        string="محادثات WhatsApp المرتبطة",
        copy=False,
    )
    wati_conversation_count = fields.Integer(
        string="عدد محادثات WhatsApp",
        compute="_compute_wati_summary",
    )
    wati_message_count = fields.Integer(
        string="رسائل WhatsApp",
        compute="_compute_wati_summary",
    )
    wati_last_message = fields.Text(
        string="آخر رسالة WhatsApp",
        compute="_compute_wati_summary",
    )
    wati_last_message_at = fields.Datetime(
        string="آخر نشاط WhatsApp",
        compute="_compute_wati_summary",
    )
    wati_last_status = fields.Char(
        string="آخر حالة WhatsApp",
        compute="_compute_wati_summary",
    )

    @staticmethod
    def _wati_normalize_phone(value):
        digits = re.sub(r"\D+", "", str(value or ""))
        if digits.startswith("00"):
            digits = digits[2:]
        if not digits:
            return ""
        if digits.startswith("966"):
            return digits
        if len(digits) == 10 and digits.startswith("05"):
            return "966" + digits[1:]
        if len(digits) == 9 and digits.startswith("5"):
            return "966" + digits
        return digits

    def _wati_customer_partner(self):
        self.ensure_one()
        if "partner_id" in self._fields and self.partner_id:
            return self.partner_id
        return self.env["res.partner"].browse()

    def _wati_partner_phones(self):
        self.ensure_one()
        values = []
        partner = self._wati_customer_partner()
        if partner:
            for field_name in ("mobile", "phone"):
                if field_name in partner._fields and partner[field_name]:
                    phone = self._wati_normalize_phone(partner[field_name])
                    if phone and phone not in values:
                        values.append(phone)

        for field_name in ("partner_phone", "phone", "mobile"):
            if field_name in self._fields and self[field_name]:
                phone = self._wati_normalize_phone(self[field_name])
                if phone and phone not in values:
                    values.append(phone)
        return values

    def _wati_find_customer_conversation(self):
        self.ensure_one()
        Conversation = self.env["wati.conversation"].sudo()

        if self.wati_conversation_ids:
            return self.wati_conversation_ids.sorted(
                key=lambda c: (
                    c.last_message_at or fields.Datetime.from_string("1970-01-01 00:00:00"),
                    c.id,
                ),
                reverse=True,
            )[:1]

        partner = self._wati_customer_partner()
        if partner:
            by_partner = Conversation.search(
                [("partner_id", "=", partner.id)],
                order="last_message_at desc, id desc",
                limit=1,
            )
            if by_partner:
                return by_partner

        phones = self._wati_partner_phones()
        if not phones:
            return Conversation.browse()

        variants = []
        for phone in phones:
            for variant in (phone, "+" + phone):
                if variant not in variants:
                    variants.append(variant)
            if phone.startswith("966") and len(phone) > 3:
                local = "0" + phone[3:]
                if local not in variants:
                    variants.append(local)

        return Conversation.search(
            [("wa_id", "in", variants)],
            order="last_message_at desc, id desc",
            limit=1,
        )

    def _wati_get_or_create_conversation(self):
        self.ensure_one()
        Conversation = self.env["wati.conversation"].sudo()
        conversation = self._wati_find_customer_conversation()
        partner = self._wati_customer_partner()

        if not conversation:
            phones = self._wati_partner_phones()
            if not phones:
                raise UserError(_("أضف رقم جوال أو هاتف للعميل قبل فتح WhatsApp."))
            phone = phones[0]
            fallback_name = False
            for field_name in ("partner_name", "name"):
                if field_name in self._fields and self[field_name]:
                    fallback_name = self[field_name]
                    break
            display_name = partner.display_name if partner else (fallback_name or phone)
            conversation = Conversation.create(
                {
                    "name": display_name,
                    "wa_id": phone,
                    "partner_id": partner.id if partner else False,
                    "sender_name": display_name,
                    "status": "local",
                    "last_message_at": fields.Datetime.now(),
                }
            )
        elif partner and not conversation.partner_id:
            conversation.write({"partner_id": partner.id})

        if self not in conversation.helpdesk_ticket_ids:
            conversation.write({"helpdesk_ticket_ids": [(4, self.id)]})
        return conversation

    def _compute_wati_summary(self):
        Message = self.env["wati.message"].sudo()
        for ticket in self:
            conversations = ticket.wati_conversation_ids
            if not conversations and ticket.id:
                conversations = ticket._wati_find_customer_conversation()

            ticket.wati_conversation_count = len(conversations)
            if not conversations:
                ticket.wati_message_count = 0
                ticket.wati_last_message = False
                ticket.wati_last_message_at = False
                ticket.wati_last_status = False
                continue

            ticket.wati_message_count = Message.search_count(
                [("conversation_id", "in", conversations.ids)]
            )
            latest = Message.search(
                [("conversation_id", "in", conversations.ids)],
                order="received_at desc, id desc",
                limit=1,
            )
            if latest:
                ticket.wati_last_message = latest.text or ""
                ticket.wati_last_message_at = latest.received_at
                ticket.wati_last_status = latest.status or ""
            else:
                conversation = conversations[0]
                ticket.wati_last_message = conversation.last_message or ""
                ticket.wati_last_message_at = conversation.last_message_at
                ticket.wati_last_status = conversation.status or ""

    def action_open_wati_inbox(self):
        self.ensure_one()
        conversation = self._wati_get_or_create_conversation()
        return {
            "type": "ir.actions.act_url",
            "url": f"/wati/inbox?conversation_id={conversation.id}",
            "target": "self",
        }

    def action_open_wati_conversations(self):
        self.ensure_one()
        conversation = self._wati_get_or_create_conversation()
        return {
            "type": "ir.actions.act_window",
            "name": _("محادثات WhatsApp"),
            "res_model": "wati.conversation",
            "view_mode": "list,form",
            "domain": [("id", "in", (self.wati_conversation_ids | conversation).ids)],
            "context": {"create": False},
        }
