import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class WatiConversationCrm(models.Model):
    _inherit = "wati.conversation"

    crm_lead_id = fields.Many2one(
        "crm.lead",
        string="فرصة / Lead CRM",
        ondelete="set null",
        index=True,
        help="سجل CRM المرتبط بهذه محادثة WhatsApp.",
    )

    def action_open_crm_lead(self):
        self.ensure_one()
        if not self.crm_lead_id:
            raise UserError(_("لا توجد فرصة CRM مرتبطة بهذه المحادثة."))
        return {
            "type": "ir.actions.act_window",
            "name": self.crm_lead_id.display_name,
            "res_model": "crm.lead",
            "res_id": self.crm_lead_id.id,
            "view_mode": "form",
            "target": "current",
        }


class CrmLeadWati(models.Model):
    _inherit = "crm.lead"

    wati_conversation_count = fields.Integer(
        string="محادثات WhatsApp",
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

    def _wati_phone_values(self):
        self.ensure_one()
        raw_values = []
        if self.partner_id:
            # Keep this runtime-compatible with Odoo editions/modules where
            # res.partner may or may not expose a separate mobile field.
            for field_name in ("mobile", "phone"):
                if field_name in self.partner_id._fields and self.partner_id[field_name]:
                    raw_values.append(self.partner_id[field_name])
        for field_name in ("mobile", "phone"):
            if field_name in self._fields and self[field_name]:
                raw_values.append(self[field_name])

        normalized = []
        for value in raw_values:
            phone = self._wati_normalize_phone(value)
            if phone and phone not in normalized:
                normalized.append(phone)
        return normalized

    def _wati_primary_phone(self):
        self.ensure_one()
        phones = self._wati_phone_values()
        return phones[0] if phones else ""

    def _wati_unlinked_candidates(self):
        self.ensure_one()
        Conversation = self.env["wati.conversation"].sudo()
        candidates = Conversation.browse()

        if self.partner_id:
            candidates = Conversation.search(
                [
                    ("partner_id", "=", self.partner_id.id),
                    ("crm_lead_id", "=", False),
                ],
                order="last_message_at desc, id desc",
            )
            if candidates:
                return candidates

        phones = self._wati_phone_values()
        if not phones:
            return candidates

        phone_variants = []
        for phone in phones:
            for variant in (phone, "+" + phone):
                if variant not in phone_variants:
                    phone_variants.append(variant)
            if phone.startswith("966") and len(phone) > 3:
                local = "0" + phone[3:]
                if local not in phone_variants:
                    phone_variants.append(local)

        return Conversation.search(
            [
                ("wa_id", "in", phone_variants),
                ("crm_lead_id", "=", False),
            ],
            order="last_message_at desc, id desc",
        )

    def _wati_linked_conversations(self, include_candidate=True):
        self.ensure_one()
        Conversation = self.env["wati.conversation"].sudo()
        linked = Conversation.search(
            [("crm_lead_id", "=", self.id)],
            order="last_message_at desc, id desc",
        )
        if linked or not include_candidate:
            return linked
        return self._wati_unlinked_candidates()

    def _wati_get_or_create_conversation(self):
        self.ensure_one()
        Conversation = self.env["wati.conversation"].sudo()

        linked = Conversation.search(
            [("crm_lead_id", "=", self.id)],
            order="last_message_at desc, id desc",
            limit=1,
        )
        if linked:
            return linked

        candidate = self._wati_unlinked_candidates()[:1]
        if candidate:
            values = {"crm_lead_id": self.id}
            if self.partner_id and not candidate.partner_id:
                values["partner_id"] = self.partner_id.id
            candidate.write(values)
            return candidate

        phone = self._wati_primary_phone()
        if not phone:
            raise UserError(_("أضف رقم جوال أو هاتف للفرصة/العميل قبل فتح WhatsApp."))

        display_name = (
            self.partner_id.display_name
            if self.partner_id
            else (self.contact_name or self.partner_name or self.name or phone)
        )
        return Conversation.create(
            {
                "name": display_name,
                "wa_id": phone,
                "partner_id": self.partner_id.id if self.partner_id else False,
                "crm_lead_id": self.id,
                "sender_name": display_name,
                "status": "local",
                "last_message_at": fields.Datetime.now(),
            }
        )

    # Only declare fields guaranteed by the Odoo 19 CRM/Contacts models.
    # Optional fields such as res.partner.mobile are read dynamically above,
    # but must not appear in @api.depends or they can crash the registry.
    @api.depends("partner_id", "phone", "partner_id.phone")
    def _compute_wati_summary(self):
        Message = self.env["wati.message"].sudo()
        for lead in self:
            if not lead.id:
                lead.wati_conversation_count = 0
                lead.wati_message_count = 0
                lead.wati_last_message = False
                lead.wati_last_message_at = False
                lead.wati_last_status = False
                continue

            conversations = lead._wati_linked_conversations(include_candidate=True)
            lead.wati_conversation_count = len(conversations)
            if not conversations:
                lead.wati_message_count = 0
                lead.wati_last_message = False
                lead.wati_last_message_at = False
                lead.wati_last_status = False
                continue

            lead.wati_message_count = Message.search_count(
                [("conversation_id", "in", conversations.ids)]
            )
            latest = Message.search(
                [("conversation_id", "in", conversations.ids)],
                order="received_at desc, id desc",
                limit=1,
            )
            if latest:
                lead.wati_last_message = latest.text or ""
                lead.wati_last_message_at = latest.received_at
                lead.wati_last_status = latest.status or ""
            else:
                conversation = conversations[0]
                lead.wati_last_message = conversation.last_message or ""
                lead.wati_last_message_at = conversation.last_message_at
                lead.wati_last_status = conversation.status or ""

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
        self._wati_get_or_create_conversation()
        return {
            "type": "ir.actions.act_window",
            "name": _("محادثات WhatsApp"),
            "res_model": "wati.conversation",
            "view_mode": "list,form",
            "domain": [("crm_lead_id", "=", self.id)],
            "context": {"create": False},
        }
