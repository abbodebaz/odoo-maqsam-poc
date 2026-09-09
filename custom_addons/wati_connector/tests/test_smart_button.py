from unittest.mock import Mock, patch

from odoo.tests.common import TransactionCase

from ..models import wati_smart_button as smart_module


class TestWatiSmartButton(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner_model = self.env["ir.model"].search(
            [("model", "=", "res.partner")], limit=1
        )
        self.partner_view = self.env.ref("base.view_partner_form")
        self.mobile_field = self.env["ir.model.fields"].search(
            [
                ("model_id", "=", self.partner_model.id),
                ("name", "=", "mobile"),
            ],
            limit=1,
        )
        self.partner = self.env["res.partner"].create(
            {"name": "Smart Button Customer", "mobile": "+966 50 123 4567"}
        )

    def _location(self, **overrides):
        values = {
            "name": "WhatsApp on Contact",
            "active": False,
            "model_id": self.partner_model.id,
            "view_id": self.partner_view.id,
            "phone_field_id": self.mobile_field.id,
            "partner_path": "self",
            "button_label": "WhatsApp",
        }
        values.update(overrides)
        return self.env["wati.smart.button.location"].create(values)

    def test_location_generates_form_extension_only_when_enabled(self):
        location = self._location()
        self.assertFalse(location.generated_view_id)

        location.active = True
        self.assertTrue(location.generated_view_id)
        self.assertTrue(location.generated_view_id.active)
        self.assertEqual(location.generated_view_id.inherit_id, self.partner_view)
        arch = str(location.generated_view_id.arch_db)
        self.assertIn("fa-whatsapp", arch)
        self.assertIn(str(location.id), arch)
        self.assertIn("wati_connector.group_wati_agent", arch)
        self.assertIn("base.group_system", arch)

        location.active = False
        self.assertFalse(location.generated_view_id.active)

    def test_location_resolves_phone_and_partner_without_custom_code(self):
        location = self._location()
        self.assertEqual(location.resolve_phone(self.partner), "966501234567")
        self.assertEqual(location.resolve_partner(self.partner), self.partner)

    def test_template_send_uses_durable_guard_and_links_conversation(self):
        location = self._location()
        template = self.env["wati.template"].create(
            {
                "name": "smart_contact_template",
                "language": "ar",
                "category": "UTILITY",
                "status": "approved",
                "source": "wati",
                "body": "Hello {{name}}",
                "variable_ids": [
                    (0, 0, {"position": 1, "name": "name", "sample_value": "Mohammed"})
                ],
            }
        )
        wizard = self.env["wati.universal.compose.wizard"].with_context(
            active_model="res.partner",
            active_id=self.partner.id,
            wati_button_rule_id=location.id,
        ).create(
            {
                "send_mode": "template",
                "template_id": template.id,
                "parameter_ids": [
                    (0, 0, {"param_name": "name", "value": self.partner.name})
                ],
            }
        )
        self.assertEqual(wizard.phone, "966501234567")
        self.assertEqual(wizard.partner_id, self.partner)

        response = Mock(status_code=200)
        with patch.object(
            smart_module.WatiIdempotency,
            "acquire_durable",
            return_value=True,
        ) as guard_mock, patch.object(
            smart_module.WatiClient,
            "send_template_messages",
            return_value=response,
        ) as send_mock:
            wizard.action_send()

        guard_mock.assert_called_once()
        payload = send_mock.call_args.args[0]
        self.assertEqual(payload["template_name"], template.name)
        self.assertEqual(
            payload["receivers"][0],
            {
                "whatsappNumber": "966501234567",
                "customParams": [{"name": "name", "value": self.partner.name}],
            },
        )
        conversation = self.env["wati.conversation"].search(
            [("wa_id", "=", "966501234567")], limit=1
        )
        self.assertTrue(conversation)
        self.assertEqual(conversation.partner_id, self.partner)

    def test_customer_timeline_matches_history_by_normalized_phone(self):
        conversation = self.env["wati.conversation"].create(
            {"name": "Historical Customer", "wa_id": "966501234567"}
        )
        message = self.env["wati.message"].create(
            {
                "name": "historical-message-1",
                "conversation_id": conversation.id,
                "wa_id": "966501234567",
                "direction": "inbound",
                "message_type": "text",
                "text": "Old message",
                "status": "Read",
            }
        )

        self.partner.invalidate_recordset()
        self.assertIn(message, self.partner.wati_timeline_message_ids)
        self.assertGreaterEqual(self.partner.wati_message_count, 1)
        action = self.partner.action_open_wati_timeline()
        self.assertEqual(action["res_model"], "wati.message")
        self.assertTrue(action["domain"])
