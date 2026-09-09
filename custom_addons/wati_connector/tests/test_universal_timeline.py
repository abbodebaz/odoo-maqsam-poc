from odoo.tests.common import TransactionCase


class TestWatiUniversalTimeline(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner_model = self.env["ir.model"].search(
            [("model", "=", "res.partner")], limit=1
        )
        self.partner_view = self.env.ref("base.view_partner_form")
        self.phone_field = self.env["ir.model.fields"].search(
            [
                ("model_id", "=", self.partner_model.id),
                ("name", "=", "phone"),
            ],
            limit=1,
        )
        self.partner = self.env["res.partner"].create(
            {"name": "Timeline Customer", "phone": "+966 55 289 8232"}
        )
        self.location = self.env["wati.smart.button.location"].create(
            {
                "name": "WhatsApp on Contact",
                "active": True,
                "model_id": self.partner_model.id,
                "view_id": self.partner_view.id,
                "phone_field_id": self.phone_field.id,
                "partner_path": "self",
                "button_label": "WhatsApp",
            }
        )

    def test_generated_view_contains_send_and_timeline_actions(self):
        arch = str(self.location.generated_view_id.arch_db)
        send_action = self.env.ref("wati_connector.action_wati_universal_compose")
        timeline_action = self.env.ref("wati_connector.action_wati_universal_timeline")
        self.assertIn(f'name="{send_action.id}"', arch)
        self.assertIn(f'name="{timeline_action.id}"', arch)
        self.assertIn("سجل WhatsApp", arch)
        self.assertIn("base.group_system", arch)

    def test_timeline_matches_current_record_by_partner_or_phone(self):
        conversation = self.env["wati.conversation"].create(
            {
                "name": self.partner.name,
                "wa_id": "966552898232",
                "partner_id": self.partner.id,
            }
        )
        message = self.env["wati.message"].create(
            {
                "name": "timeline-message-1",
                "conversation_id": conversation.id,
                "wa_id": "966552898232",
                "direction": "inbound",
                "message_type": "text",
                "text": "مرحبا",
                "status": "Read",
            }
        )

        values = self.env["wati.universal.timeline.wizard"].with_context(
            active_model="res.partner",
            active_id=self.partner.id,
            wati_button_rule_id=self.location.id,
        ).default_get(
            ["rule_id", "source_model", "source_res_id", "record_name", "partner_id", "phone"]
        )
        wizard = self.env["wati.universal.timeline.wizard"].create(values)

        self.assertEqual(wizard.phone, "966552898232")
        self.assertEqual(wizard.partner_id, self.partner)
        self.assertIn(message, wizard.message_ids)
        self.assertEqual(wizard.message_count, 1)
        action = wizard.action_open_full_timeline()
        self.assertEqual(action["res_model"], "wati.message")
        self.assertTrue(action["domain"])
