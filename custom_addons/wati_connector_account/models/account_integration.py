from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.wati_connector.utils.phone import equivalent_variants, normalize_whatsapp_number


_CUSTOMER_MOVE_TYPES = {"out_invoice", "out_refund", "out_receipt"}


class WatiConversationAccount(models.Model):
    _inherit = "wati.conversation"

    account_move_ids = fields.Many2many(
        "account.move", "wati_account_move_conversation_rel", "conversation_id", "move_id",
        string="Associated invoices", copy=False,
    )
    account_move_count = fields.Integer(string="Number of invoices", compute="_compute_account_move_count")

    def _compute_account_move_count(self):
        for conversation in self:
            conversation.account_move_count = len(conversation.account_move_ids)

    def action_open_account_moves(self):
        self.ensure_one()
        moves = self.account_move_ids.filtered(lambda move: move.move_type in _CUSTOMER_MOVE_TYPES)
        if not moves:
            raise UserError(_("There are no customer invoices associated with this conversation."))
        if len(moves) == 1:
            return {"type": "ir.actions.act_window", "name": moves.display_name, "res_model": "account.move", "res_id": moves.id, "view_mode": "form", "target": "current"}
        return {"type": "ir.actions.act_window", "name": _("Client invoices"), "res_model": "account.move", "view_mode": "list,form", "domain": [("id", "in", moves.ids)], "target": "current"}


class AccountMoveWati(models.Model):
    _inherit = "account.move"

    wati_conversation_ids = fields.Many2many(
        "wati.conversation", "wati_account_move_conversation_rel", "move_id", "conversation_id",
        string="Conversations WhatsApp associated", copy=False,
    )
    wati_conversation_count = fields.Integer(string="Number of conversations WhatsApp", compute="_compute_wati_summary")
    wati_message_count = fields.Integer(string="Messages WhatsApp", compute="_compute_wati_summary")
    wati_last_message = fields.Text(string="Last message WhatsApp", compute="_compute_wati_summary")
    wati_last_message_at = fields.Datetime(string="Latest activity WhatsApp", compute="_compute_wati_summary")
    wati_last_status = fields.Char(string="Latest case WhatsApp", compute="_compute_wati_summary")

    def _wati_validate_customer_move(self):
        self.ensure_one()
        if self.move_type not in _CUSTOMER_MOVE_TYPES:
            raise UserError(_("WhatsApp Available for customer invoices and credit notes only."))
        if not self.partner_id:
            raise UserError(_("Select the client first before opening WhatsApp."))

    def _wati_partner_phones(self):
        self.ensure_one()
        if not self.partner_id:
            return []
        values = []
        for field_name in ("mobile", "phone"):
            if field_name in self.partner_id._fields and self.partner_id[field_name]:
                phone = normalize_whatsapp_number(self.partner_id[field_name])
                if phone and phone not in values:
                    values.append(phone)
        return values

    def _wati_find_customer_conversation(self):
        self.ensure_one()
        Conversation = self.env["wati.conversation"].sudo()
        if self.wati_conversation_ids:
            return self.wati_conversation_ids.sorted(
                key=lambda c: (c.last_message_at or fields.Datetime.from_string("1970-01-01 00:00:00"), c.id), reverse=True,
            )[:1]
        if self.partner_id:
            by_partner = Conversation.search([("partner_id", "=", self.partner_id.id)], order="last_message_at desc, id desc", limit=1)
            if by_partner:
                return by_partner
        variants = []
        for phone in self._wati_partner_phones():
            for variant in equivalent_variants(phone):
                if variant not in variants:
                    variants.append(variant)
        return Conversation.search([("wa_id", "in", variants)], order="last_message_at desc, id desc", limit=1) if variants else Conversation.browse()

    def _wati_get_or_create_conversation(self):
        self.ensure_one()
        self._wati_validate_customer_move()
        Conversation = self.env["wati.conversation"].sudo()
        conversation = self._wati_find_customer_conversation()
        if not conversation:
            phones = self._wati_partner_phones()
            if not phones:
                raise UserError(_("Add the customer’s mobile number or phone before unlocking WhatsApp."))
            phone = phones[0]
            display_name = self.partner_id.display_name or self.name or phone
            conversation = Conversation.create({"name": display_name, "wa_id": phone, "partner_id": self.partner_id.id, "sender_name": display_name, "status": "local", "last_message_at": fields.Datetime.now()})
        elif not conversation.partner_id:
            conversation.partner_id = self.partner_id
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
            conversations = move.wati_conversation_ids or (move._wati_find_customer_conversation() if move.id else self.env["wati.conversation"].browse())
            move.wati_conversation_count = len(conversations)
            if not conversations:
                move.wati_message_count = 0
                move.wati_last_message = False
                move.wati_last_message_at = False
                move.wati_last_status = False
                continue
            move.wati_message_count = Message.search_count([("conversation_id", "in", conversations.ids)])
            latest = Message.search([("conversation_id", "in", conversations.ids)], order="received_at desc, id desc", limit=1)
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
        return {"type": "ir.actions.act_url", "url": f"/wati/inbox?conversation_id={conversation.id}", "target": "self"}

    def action_open_wati_conversations(self):
        self.ensure_one()
        conversation = self._wati_get_or_create_conversation()
        return {"type": "ir.actions.act_window", "name": _("Conversations WhatsApp"), "res_model": "wati.conversation", "view_mode": "list,form", "domain": [("id", "in", (self.wati_conversation_ids | conversation).ids)], "context": {"create": False}}


class WatiAutomationRuleAccountPresets(models.Model):
    _inherit = "wati.automation.rule"

    @api.model
    def _wati_preset_definitions(self):
        definitions = dict(super()._wati_preset_definitions())
        definitions.update({
            "invoice_posted": {
                "label": _("Invoices · When deported"),
                "model": "account.move",
                "field": "state",
                "target": "posted",
                "recipient_path": "partner_id.phone",
                "name": _("Invoices · Send on migration"),
            },
            "invoice_paid": {
                "label": _("Invoices · Upon payment"),
                "model": "account.move",
                "field": "payment_state",
                "target": "paid",
                "recipient_path": "partner_id.phone",
                "name": _("Invoices · Submit upon payment"),
            },
        })
        return definitions
