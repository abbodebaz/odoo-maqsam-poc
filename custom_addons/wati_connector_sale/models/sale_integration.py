from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.wati_connector.utils.phone import equivalent_variants, normalize_whatsapp_number


class WatiConversationSale(models.Model):
    _inherit = "wati.conversation"

    sale_order_ids = fields.Many2many(
        "sale.order", "wati_sale_order_conversation_rel", "conversation_id", "sale_order_id",
        string="عروض وأوامر البيع المرتبطة", copy=False,
    )
    sale_order_count = fields.Integer(string="عدد عروض وأوامر البيع", compute="_compute_sale_order_count")

    def _compute_sale_order_count(self):
        for conversation in self:
            conversation.sale_order_count = len(conversation.sale_order_ids)

    def action_open_sale_orders(self):
        self.ensure_one()
        if not self.sale_order_ids:
            raise UserError(_("لا توجد عروض أو أوامر بيع مرتبطة بهذه المحادثة."))
        if len(self.sale_order_ids) == 1:
            return {"type": "ir.actions.act_window", "name": self.sale_order_ids.display_name, "res_model": "sale.order", "res_id": self.sale_order_ids.id, "view_mode": "form", "target": "current"}
        return {"type": "ir.actions.act_window", "name": _("عروض / أوامر البيع"), "res_model": "sale.order", "view_mode": "list,form", "domain": [("id", "in", self.sale_order_ids.ids)], "target": "current"}


class SaleOrderWati(models.Model):
    _inherit = "sale.order"

    wati_conversation_ids = fields.Many2many(
        "wati.conversation", "wati_sale_order_conversation_rel", "sale_order_id", "conversation_id",
        string="سجل محادثات WhatsApp", copy=False,
    )
    wati_conversation_count = fields.Integer(string="عدد محادثات WhatsApp", compute="_compute_wati_summary")
    wati_message_count = fields.Integer(string="رسائل WhatsApp", compute="_compute_wati_summary")
    wati_last_message = fields.Text(string="آخر رسالة WhatsApp", compute="_compute_wati_summary")
    wati_last_message_at = fields.Datetime(string="آخر نشاط WhatsApp", compute="_compute_wati_summary")
    wati_last_status = fields.Char(string="آخر حالة WhatsApp", compute="_compute_wati_summary")

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
        Conversation = self.env["wati.conversation"].sudo()
        conversation = self._wati_find_customer_conversation()
        if not conversation:
            phones = self._wati_partner_phones()
            if not phones:
                raise UserError(_("أضف رقم جوال أو هاتف للعميل قبل فتح WhatsApp."))
            phone = phones[0]
            display_name = self.partner_id.display_name or self.name or phone
            conversation = Conversation.create({"name": display_name, "wa_id": phone, "partner_id": self.partner_id.id, "sender_name": display_name, "status": "local", "last_message_at": fields.Datetime.now()})
        elif self.partner_id and not conversation.partner_id:
            conversation.partner_id = self.partner_id
        if self not in conversation.sale_order_ids:
            conversation.write({"sale_order_ids": [(4, self.id)]})
        return conversation

    def _compute_wati_summary(self):
        Message = self.env["wati.message"].sudo()
        for order in self:
            conversations = order.wati_conversation_ids or (order._wati_find_customer_conversation() if order.id else self.env["wati.conversation"].browse())
            order.wati_conversation_count = len(conversations)
            if not conversations:
                order.wati_message_count = 0
                order.wati_last_message = False
                order.wati_last_message_at = False
                order.wati_last_status = False
                continue
            order.wati_message_count = Message.search_count([("conversation_id", "in", conversations.ids)])
            latest = Message.search([("conversation_id", "in", conversations.ids)], order="received_at desc, id desc", limit=1)
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
        return {"type": "ir.actions.act_url", "url": f"/wati/inbox?conversation_id={conversation.id}", "target": "self"}

    def action_open_wati_conversations(self):
        self.ensure_one()
        conversation = self._wati_get_or_create_conversation()
        return {"type": "ir.actions.act_window", "name": _("محادثات WhatsApp"), "res_model": "wati.conversation", "view_mode": "list,form", "domain": [("id", "in", (self.wati_conversation_ids | conversation).ids)], "context": {"create": False}}


class WatiAutomationRuleSalePresets(models.Model):
    _inherit = "wati.automation.rule"

    @api.model
    def _wati_preset_definitions(self):
        definitions = dict(super()._wati_preset_definitions())
        definitions["sale_confirmed"] = {
            "label": _("المبيعات · عند تأكيد الطلب"),
            "model": "sale.order",
            "field": "state",
            "target": "sale",
            "recipient_path": "partner_id.phone",
            "name": _("المبيعات · إرسال عند تأكيد الطلب"),
        }
        return definitions
