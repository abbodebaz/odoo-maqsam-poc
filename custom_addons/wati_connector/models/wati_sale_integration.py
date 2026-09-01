import re

from odoo import _, fields, models
from odoo.exceptions import UserError


class WatiConversationSale(models.Model):
    _inherit = "wati.conversation"

    sale_order_ids = fields.Many2many(
        "sale.order",
        "wati_sale_order_conversation_rel",
        "conversation_id",
        "sale_order_id",
        string="عروض وأوامر البيع المرتبطة",
        copy=False,
    )
    sale_order_count = fields.Integer(
        string="عدد عروض وأوامر البيع",
        compute="_compute_sale_order_count",
    )

    def _compute_sale_order_count(self):
        for conversation in self:
            conversation.sale_order_count = len(conversation.sale_order_ids)

    def action_open_sale_orders(self):
        self.ensure_one()
        if not self.sale_order_ids:
            raise UserError(_("لا توجد عروض أو أوامر بيع مرتبطة بهذه المحادثة."))
        if len(self.sale_order_ids) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": self.sale_order_ids.display_name,
                "res_model": "sale.order",
                "res_id": self.sale_order_ids.id,
                "view_mode": "form",
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("عروض / أوامر البيع"),
            "res_model": "sale.order",
            "view_mode": "list,form",
            "domain": [("id", "in", self.sale_order_ids.ids)],
            "target": "current",
        }


class SaleOrderWati(models.Model):
    _inherit = "sale.order"

    wati_conversation_ids = fields.Many2many(
        "wati.conversation",
        "wati_sale_order_conversation_rel",
        "sale_order_id",
        "conversation_id",
        string="سجل محادثات WhatsApp",
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

    def _wati_partner_phones(self):
        self.ensure_one()
        partner = self.partner_id
        if not partner:
            return []

        values = []
        # Odoo installations can differ on whether `mobile` exists on res.partner.
        # Read it only when the field is actually present; `phone` is the portable baseline.
        for field_name in ("mobile", "phone"):
            if field_name in partner._fields and partner[field_name]:
                phone = self._wati_normalize_phone(partner[field_name])
                if phone and phone not in values:
                    values.append(phone)
        return values

    def _wati_find_customer_conversation(self):
        self.ensure_one()
        Conversation = self.env["wati.conversation"].sudo()

        if self.wati_conversation_ids:
            return self.wati_conversation_ids.sorted(
                key=lambda c: (c.last_message_at or fields.Datetime.from_string("1970-01-01 00:00:00"), c.id),
                reverse=True,
            )[:1]

        if self.partner_id:
            by_partner = Conversation.search(
                [("partner_id", "=", self.partner_id.id)],
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

        if not conversation:
            phones = self._wati_partner_phones()
            if not phones:
                raise UserError(_("أضف رقم جوال أو هاتف للعميل قبل فتح WhatsApp."))
            phone = phones[0]
            display_name = self.partner_id.display_name or self.name or phone
            conversation = Conversation.create(
                {
                    "name": display_name,
                    "wa_id": phone,
                    "partner_id": self.partner_id.id,
                    "sender_name": display_name,
                    "status": "local",
                    "last_message_at": fields.Datetime.now(),
                }
            )
        elif self.partner_id and not conversation.partner_id:
            conversation.write({"partner_id": self.partner_id.id})

        if self not in conversation.sale_order_ids:
            conversation.write({"sale_order_ids": [(4, self.id)]})
        return conversation

    def _compute_wati_summary(self):
        Message = self.env["wati.message"].sudo()
        for order in self:
            conversations = order.wati_conversation_ids
            # For older orders opened before the explicit relation existed, show the
            # customer's existing conversation without silently writing during compute.
            if not conversations and order.id:
                conversations = order._wati_find_customer_conversation()

            order.wati_conversation_count = len(conversations)
            if not conversations:
                order.wati_message_count = 0
                order.wati_last_message = False
                order.wati_last_message_at = False
                order.wati_last_status = False
                continue

            order.wati_message_count = Message.search_count(
                [("conversation_id", "in", conversations.ids)]
            )
            latest = Message.search(
                [("conversation_id", "in", conversations.ids)],
                order="received_at desc, id desc",
                limit=1,
            )
            if latest:
                order.wati_last_message = latest.text or ""
                order.wati_last_message_at = latest.received_at
                order.wati_last_status = latest.status or ""
            else:
                conversation = conversations[0]
                order.wati_last_message = conversation.last_message or ""
                order.wati_last_message_at = conversation.last_message_at
                order.wati_last_status = conversation.status or ""

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
