from odoo import fields, models

from ..utils.phone import normalize_whatsapp_number


class WatiSmartButtonLocationPhoneCompat(models.Model):
    _inherit = "wati.smart.button.location"

    def _auto_detect_phone_and_partner(self):
        """Keep auto-detection valid when a target partner model has no mobile field."""
        result = super()._auto_detect_phone_and_partner()
        Partner = self.env["res.partner"]
        for record in self:
            path = (record.phone_path or "").strip()
            if not path or not path.endswith(".mobile"):
                continue
            if "mobile" in Partner._fields:
                continue
            if "phone" in Partner._fields:
                record.phone_path = path[: -len("mobile")] + "phone"
        return result


class ResPartnerWatiTimelinePhoneCompat(models.Model):
    _inherit = "res.partner"

    # Use a distinct compute method name so Odoo does not merge dependency
    # metadata from the earlier implementation that referenced optional fields.
    wati_timeline_message_ids = fields.Many2many(
        "wati.message",
        string="WhatsApp Timeline",
        compute="_compute_wati_timeline_runtime_safe",
    )
    wati_message_count = fields.Integer(
        string="رسائل WhatsApp",
        compute="_compute_wati_timeline_runtime_safe",
    )
    wati_last_message_at = fields.Datetime(
        string="آخر تواصل WhatsApp",
        compute="_compute_wati_timeline_runtime_safe",
    )

    def _wati_timeline_domain(self):
        """Build timeline matching only from phone fields present in this Odoo build."""
        self.ensure_one()
        phones = set()
        for field_name in ("mobile", "phone"):
            if field_name not in self._fields:
                continue
            normalized = normalize_whatsapp_number(self[field_name])
            if normalized:
                phones.add(normalized)

        linked = [("conversation_id.partner_id", "=", self.id)]
        if not phones:
            return linked
        return [
            "|",
            ("conversation_id.partner_id", "=", self.id),
            ("wa_id", "in", sorted(phones)),
        ]

    def _compute_wati_timeline_runtime_safe(self):
        """Non-stored timeline compute with zero hard dependencies on optional fields."""
        Message = self.env["wati.message"].sudo()
        for partner in self:
            messages = Message.search(
                partner._wati_timeline_domain(),
                order="received_at desc, id desc",
            )
            partner.wati_timeline_message_ids = messages
            partner.wati_message_count = len(messages)
            partner.wati_last_message_at = messages[:1].received_at if messages else False
