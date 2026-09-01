import re

from odoo import _, fields, models
from odoo.exceptions import UserError


_CUSTOMER_MOVE_TYPES = {"out_invoice", "out_refund", "out_receipt"}


class WatiConversationAccount(models.Model):
    _inherit = "wati.conversation"

    account_move_ids = fields.Many2many(
        "account.move",
        "wati_account_move_conversation_rel",
        "conversation_id",
        "move_id",
        string="الفواتير المرتبطة",
        copy=False,
    )
    account_move_count = fields.Integer(
        string="عدد الفواتير",
        compute="_compute_account_move_count",
    )

    def _compute_account_move_count(self):
        for conversation in self:
            conversation.account_move_count = len(conversation.account_move_ids)

    def action_open_account_moves(self):
        self.ensure_one()
        moves = self.account_move_ids.filtered(lambda move: move.move_type in _CUSTOMER_MOVE_TYPES)
        if not moves:
            raise UserError(_("لا توجد فواتير عميل مرتبطة بهذه المحادثة."))
        if len(moves) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": moves.display_name,
                "res_model": "account.move",
                "res_id": moves.id,
                "view_mode": "form",
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("فواتير العميل"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", moves.ids)],
            "target": "current",
        }


class AccountMoveWati(models.Model):
    _inherit = "account.move"

    wati_conversation_ids = fields.Many2many(
        "wati.conversation",
        "wati_account_move_conversation_rel",
        "move_id",
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

    def _wati_validate_customer_move(self):
        self.ensure_one()
        if self.move_type not in _CUSTOMER_MOVE_TYPES:
            raise UserError(_("WhatsApp متاح لفواتير العملاء والإشعارات الدائنة فقط."))
        if not self.partner_id:
            raise UserError(_("حدد العميل أولًا قبل فتح WhatsApp."))

    def _wati_partner_phones(self):
        self.ensure_one()
        partner = self.partner_id
        if not partner:
            return []
        values = []
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
                key=lambda conversation: (
                    conversation.last_message_at or fields.Datetime.from_string("1970-01-01 00:00:00"),
                    conversation.id,
                ),
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
        self._wati_validate_customer_move()
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

        if self not in conversation.account_move_ids:
            conversation.write({"account_move_ids": [(4, self.id)]})
        return conversation

    def _compute_wati_summary(self):
        Message = self.env["wati.message"].sudo()
        for move in self:
            if move.move_type not in _CUSTOMER_MOVE_TYPES:
                move.wati_conversation_count = 0
                move.wati_message_count = 0
                move.wati_last_message = False
                move.wati_last_message_at = False
                move.wati_last_status = False
                continue

            conversations = move.wati_conversation_ids
            if not conversations and move.id:
                conversations = move._wati_find_customer_conversation()

            move.wati_conversation_count = len(conversations)
            if not conversations:
                move.wati_message_count = 0
                move.wati_last_message = False
                move.wati_last_message_at = False
                move.wati_last_status = False
                continue

            move.wati_message_count = Message.search_count(
                [("conversation_id", "in", conversations.ids)]
            )
            latest = Message.search(
                [("conversation_id", "in", conversations.ids)],
                order="received_at desc, id desc",
                limit=1,
            )
            if latest:
                move.wati_last_message = latest.text or ""
                move.wati_last_message_at = latest.received_at
                move.wati_last_status = latest.status or ""
            else:
                conversation = conversations[0]
                move.wati_last_message = conversation.last_message or ""
                move.wati_last_message_at = conversation.last_message_at
                move.wati_last_status = conversation.status or ""

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
