from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.wati_connector.utils.phone import equivalent_variants, normalize_whatsapp_number


class WatiConversationProject(models.Model):
    _inherit = "wati.conversation"

    project_task_ids = fields.Many2many(
        "project.task",
        "wati_project_task_conversation_rel",
        "conversation_id",
        "task_id",
        string="Associated project tasks",
        copy=False,
    )
    project_task_count = fields.Integer(
        string="Number of project tasks",
        compute="_compute_project_task_count",
    )

    def _compute_project_task_count(self):
        for conversation in self:
            conversation.project_task_count = len(conversation.project_task_ids)

    def action_open_project_tasks(self):
        self.ensure_one()
        if not self.project_task_ids:
            raise UserError(_("There are no project tasks associated with this conversation."))
        if len(self.project_task_ids) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": self.project_task_ids.display_name,
                "res_model": "project.task",
                "res_id": self.project_task_ids.id,
                "view_mode": "form",
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("Project tasks"),
            "res_model": "project.task",
            "view_mode": "list,form",
            "domain": [("id", "in", self.project_task_ids.ids)],
            "target": "current",
        }


class ProjectTaskWati(models.Model):
    _inherit = "project.task"

    wati_conversation_ids = fields.Many2many(
        "wati.conversation",
        "wati_project_task_conversation_rel",
        "task_id",
        "conversation_id",
        string="Conversations WhatsApp associated",
        copy=False,
    )
    wati_conversation_count = fields.Integer(string="Number of conversations WhatsApp", compute="_compute_wati_summary")
    wati_message_count = fields.Integer(string="Messages WhatsApp", compute="_compute_wati_summary")
    wati_last_message = fields.Text(string="Last message WhatsApp", compute="_compute_wati_summary")
    wati_last_message_at = fields.Datetime(string="Latest activity WhatsApp", compute="_compute_wati_summary")
    wati_last_status = fields.Char(string="Latest case WhatsApp", compute="_compute_wati_summary")

    def _wati_customer_partner(self):
        self.ensure_one()
        if "partner_id" in self._fields and self.partner_id:
            return self.partner_id
        project = self.project_id
        if project and "partner_id" in project._fields and project.partner_id:
            return project.partner_id
        return self.env["res.partner"].browse()

    def _wati_partner_phones(self):
        self.ensure_one()
        partner = self._wati_customer_partner()
        if not partner:
            return []
        values = []
        for field_name in ("mobile", "phone"):
            if field_name in partner._fields and partner[field_name]:
                phone = normalize_whatsapp_number(partner[field_name])
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

        variants = []
        for phone in self._wati_partner_phones():
            for variant in equivalent_variants(phone):
                if variant not in variants:
                    variants.append(variant)
        if not variants:
            return Conversation.browse()
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
                raise UserError(_("Add a mobile or phone number for the task client or project client before opening WhatsApp."))
            phone = phones[0]
            display_name = partner.display_name if partner else (self.name or phone)
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
            conversation.partner_id = partner

        if self not in conversation.project_task_ids:
            conversation.write({"project_task_ids": [(4, self.id)]})
        return conversation

    def _compute_wati_summary(self):
        Message = self.env["wati.message"].sudo()
        for task in self:
            conversations = task.wati_conversation_ids
            if not conversations and task.id:
                conversations = task._wati_find_customer_conversation()
            task.wati_conversation_count = len(conversations)
            if not conversations:
                task.wati_message_count = 0
                task.wati_last_message = False
                task.wati_last_message_at = False
                task.wati_last_status = False
                continue
            task.wati_message_count = Message.search_count([("conversation_id", "in", conversations.ids)])
            latest = Message.search(
                [("conversation_id", "in", conversations.ids)],
                order="received_at desc, id desc",
                limit=1,
            )
            if latest:
                task.wati_last_message = latest.text or ""
                task.wati_last_message_at = latest.received_at
                task.wati_last_status = latest.status or ""
            else:
                conversation = conversations[0]
                task.wati_last_message = conversation.last_message or ""
                task.wati_last_message_at = conversation.last_message_at
                task.wati_last_status = conversation.status or ""

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
            "name": _("Conversations WhatsApp"),
            "res_model": "wati.conversation",
            "view_mode": "list,form",
            "domain": [("id", "in", (self.wati_conversation_ids | conversation).ids)],
            "context": {"create": False},
        }
