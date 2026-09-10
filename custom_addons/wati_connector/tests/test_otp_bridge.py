from unittest.mock import Mock, patch

from odoo.tests.common import TransactionCase

from ..models import wati_otp_bridge as otp_module


class TestWatiOtpBridge(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner_model = self.env["ir.model"].search(
            [("model", "=", "res.partner")], limit=1
        )
        self.otp_field = self.env["ir.model.fields"].search(
            [("model_id", "=", self.partner_model.id), ("name", "=", "ref")],
            limit=1,
        )
        self.mobile_field = self.env["ir.model.fields"].search(
            [("model_id", "=", self.partner_model.id), ("name", "=", "mobile")],
            limit=1,
        )
        self.template = self.env["wati.template"].create(
            {
                "name": "test_driver_otp",
                "language": "ar",
                "category": "AUTHENTICATION",
                "status": "approved",
                "source": "wati",
                "body": "رمز التحقق الخاص بك هو {{1}}",
            }
        )
        self.partner = self.env["res.partner"].create(
            {
                "name": "OTP Test Driver",
                "mobile": "966500000111",
                "ref": "654321",
            }
        )

    def _bridge(self, **overrides):
        values = {
            "name": "Driver Login OTP",
            "technical_key": "driver_login_test",
            "trigger_mode": "field",
            "model_id": self.partner_model.id,
            "otp_field_id": self.otp_field.id,
            "phone_field_id": self.mobile_field.id,
            "template_id": self.template.id,
            "code_param_name": "1",
            "active": True,
        }
        values.update(overrides)
        return self.env["wati.otp.bridge"].create(values)

    def test_no_code_bridge_creates_native_odoo_automation(self):
        bridge = self._bridge()
        self.assertTrue(bridge.base_automation_id)
        self.assertTrue(bridge.base_automation_id.active)
        self.assertEqual(bridge.base_automation_id.model_id, self.partner_model)
        self.assertIn(self.otp_field, bridge.base_automation_id.trigger_field_ids)
        self.assertTrue(bridge.server_action_id)

    def test_no_code_send_uses_auth_template_and_never_logs_plain_otp(self):
        bridge = self._bridge()
        response = Mock()
        response.text = "accepted otp=654321"
        response.reason = "OK"

        with patch.object(
            otp_module.WatiIdempotency,
            "acquire_durable",
            return_value=True,
        ), patch.object(
            otp_module.WatiClient,
            "send_template_messages",
            return_value=response,
        ) as send_mock:
            self.assertTrue(bridge._execute_record(self.partner))

        payload = send_mock.call_args.args[0]
        self.assertEqual(payload["template_name"], self.template.name)
        receiver = payload["receivers"][0]
        self.assertEqual(receiver["whatsappNumber"], "966500000111")
        self.assertEqual(
            receiver["customParams"],
            [{"name": "1", "value": "654321"}],
        )

        log = self.env["wati.otp.log"].search(
            [("bridge_id", "=", bridge.id)], limit=1
        )
        self.assertEqual(log.status, "sent")
        self.assertNotIn("654321", log.provider_excerpt or "")
        self.assertNotEqual(log.code_fingerprint, "654321")
        self.assertTrue(log.code_fingerprint)
        self.assertTrue((log.phone_masked or "").endswith("0111"))
        self.assertNotIn("966500000111", log.phone_masked or "")

    def test_durable_duplicate_guard_stops_second_provider_send(self):
        bridge = self._bridge()
        with patch.object(
            otp_module.WatiIdempotency,
            "acquire_durable",
            return_value=False,
        ), patch.object(
            otp_module.WatiClient,
            "send_template_messages",
        ) as send_mock:
            self.assertFalse(bridge._execute_record(self.partner))

        send_mock.assert_not_called()
        log = self.env["wati.otp.log"].search(
            [("bridge_id", "=", bridge.id)], order="id desc", limit=1
        )
        self.assertEqual(log.status, "skipped")
        self.assertIn("منع", log.error_message)

    def test_integration_hook_can_send_without_monitoring_an_otp_field(self):
        bridge = self.env["wati.otp.bridge"].create(
            {
                "name": "Driver Hook OTP",
                "technical_key": "driver_hook_test",
                "trigger_mode": "hook",
                "model_id": self.partner_model.id,
                "phone_field_id": self.mobile_field.id,
                "template_id": self.template.id,
                "code_param_name": "1",
                "active": True,
            }
        )
        self.assertFalse(bridge.base_automation_id)

        response = Mock(text="accepted", reason="OK")
        with patch.object(
            otp_module.WatiIdempotency,
            "acquire_durable",
            return_value=True,
        ), patch.object(
            otp_module.WatiClient,
            "send_template_messages",
            return_value=response,
        ) as send_mock:
            sent = self.env["wati.otp.bridge"].send_by_key(
                "driver_hook_test",
                record=self.partner,
                code="246810",
            )

        self.assertTrue(sent)
        receiver = send_mock.call_args.args[0]["receivers"][0]
        self.assertEqual(receiver["whatsappNumber"], "966500000111")
        self.assertEqual(receiver["customParams"][0]["value"], "246810")

    def test_auto_detect_finds_partner_mobile_without_guessing_unrelated_otp(self):
        bridge = self.env["wati.otp.bridge"].create(
            {
                "name": "Discovery",
                "technical_key": "discovery_test",
                "trigger_mode": "field",
                "model_id": self.partner_model.id,
                "template_id": self.template.id,
                "active": False,
            }
        )
        bridge.action_auto_detect_fields()
        self.assertEqual(bridge.phone_field_id.name, "mobile")
        self.assertFalse(bridge.otp_field_id)
