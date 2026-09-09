from odoo import _, api, fields, models

from ..utils.phone import normalize_whatsapp_number


def _clean(value):
    if value in (None, False):
        return ""
    return str(value).strip()


class WatiUniversalTimelineWizard(models.TransientModel):
    _name = "wati.universal.timeline.wizard"
    _description = "Universal WhatsApp Timeline"

    rule_id = fields.Many2one("wati.smart.button.location", string="مكان الزر", readonly=True)
    source_model = fields.Char(string="الموديل", readonly=True)
    source_res_id = fields.Integer(string="رقم السجل", readonly=True)
    record_name = fields.Char(string="السجل", readonly=True)
    partner_id = fields.Many2one("res.partner", string="العميل", readonly=True)
    phone = fields.Char(string="رقم WhatsApp", readonly=True)
    message_ids = fields.Many2many(
        "wati.message",
        string="WhatsApp Timeline",
        compute="_compute_timeline",
    )
    message_count = fields.Integer(string="عدد الرسائل", compute="_compute_timeline")
    last_message_at = fields.Datetime(string="آخر تواصل", compute="_compute_timeline")

    @api.model
    def default_get(self, field_list):
        values = super().default_get(field_list)
        context = self.env.context
        rule = self.env["wati.smart.button.location"].sudo().browse(
            int(context.get("wati_button_rule_id") or 0)
        ).exists()
        model_name = _clean(context.get("active_model"))
        res_id = int(context.get("active_id") or 0)
        if not rule or not model_name or not res_id or rule.model_name != model_name:
            return values
        record = self.env[model_name].browse(res_id).exists()
        if not record:
            return values
        partner = rule.resolve_partner(record)
        values.update(
            {
                "rule_id": rule.id,
                "source_model": model_name,
                "source_res_id": res_id,
                "record_name": record.display_name,
                "phone": rule.resolve_phone(record),
                "partner_id": partner.id if partner else False,
            }
        )
        return values

    def _timeline_domain(self):
        self.ensure_one()
        phone = normalize_whatsapp_number(self.phone)
        partner_id = self.partner_id.id if self.partner_id else False
        if partner_id and phone:
            return [
                "|",
                ("conversation_id.partner_id", "=", partner_id),
                ("wa_id", "=", phone),
            ]
        if partner_id:
            return [("conversation_id.partner_id", "=", partner_id)]
        if phone:
            return [("wa_id", "=", phone)]
        return [("id", "=", 0)]

    @api.depends("rule_id", "source_model", "source_res_id", "phone", "partner_id")
    def _compute_timeline(self):
        Message = self.env["wati.message"].sudo()
        for wizard in self:
            messages = Message.search(
                wizard._timeline_domain(),
                order="received_at desc, id desc",
            )
            wizard.message_ids = messages
            wizard.message_count = len(messages)
            wizard.last_message_at = messages[:1].received_at if messages else False

    def action_open_full_timeline(self):
        self.ensure_one()
        action = self.env.ref("wati_connector.action_wati_messages").read()[0]
        action["name"] = _("WhatsApp · %s") % (self.record_name or self.phone or "")
        action["domain"] = self._timeline_domain()
        return action


class WatiSmartButtonTimeline(models.Model):
    _inherit = "wati.smart.button.location"

    def _generated_arch(self):
        self.ensure_one()
        arch = super()._generated_arch()
        action = self.env.ref("wati_connector.action_wati_universal_timeline")
        timeline_button = (
            f'<button name="{action.id}" type="action" string="سجل WhatsApp" '
            'icon="fa-history" class="btn-secondary" '
            'groups="wati_connector.group_wati_agent,base.group_system" '
            f'context="{{\'wati_button_rule_id\': {self.id}}}"/>'
        )
        if "</xpath>" not in arch:
            return arch
        return arch.replace("</xpath>", f"{timeline_button}</xpath>", 1)

    @api.model
    def _repair_timeline_buttons(self):
        for record in self.sudo().search([("active", "=", True)]):
            record._sync_generated_view()
        return True
