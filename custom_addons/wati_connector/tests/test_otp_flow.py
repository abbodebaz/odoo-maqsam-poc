from unittest.mock import Mock, patch

from odoo.tests.common import TransactionCase

from ..models import wati_otp_flow as otp_flow_module


class TestManagedOtpFlow(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner_model = self.env["ir.model"].search(
            [("model", "=", "res.partner")], limit=1
        )
        self.template = self.env["wati.template"].create(
            {
                "name": "service_complete_otp",
                "language": "en",
                "category": "MARKETING",
                "status": "approved",
                "source": "wati",
                "body": "Your service is complete. Confirmation code: {{1}}",
            }
        )
        self.partner = self.env["res.partner"].create(
            {"name": "Managed OTP Customer", "mobile": "966500000222"}
        )

    def _flow(self, **overrides):
        values = {
            "name": "Service Completion",
            "technical_key": "service_completion_test",
            "model_id": self.partner_model.id,
            "trigger_method": "manual",
            "recipient_mode": "auto",
            "template_id": self.template.id,
            "validity_minutes": 10,
            "max_attempts": 3,
            "active": True,
        }
        values.update(overrides)
        flow = self.env["wati.otp.flow"].create(values)
        self.env["wati.otp.variable.binding"].create(
            {
                "flow_id": flow.id,
                "sequence": 1,
                "variable_name": "1",
                "source_type": "otp",
            }
        )
        return flow

    def test_managed_flow_accepts_approved_marketing_template(self):
        flow = self._flow()
        self.assertEqual(flow.template_id.category, "MARKETING")
        self.assertEqual(flow.mapping_state, "ready")
        self.assertTrue(flow.manual_action_id)
        self.assertEqual(flow.manual_action_id.binding_model_id, self.partner_model)

    def test_request_generates_secure_code_sends_it_and_does_not_store_plaintext(self):
        flow = self._flow()
        response = Mock(text="accepted", reason="OK")
        with patch.object(
            otp_flow_module.WatiIdempotency,
            "acquire_durable",
            return_value=True,
        ), patch.object(
            otp_flow_module.WatiClient,
            "send_template_messages",
            return_value=response,
        ) as send_mock:
            transaction = flow.request_otp(self.partner)

        self.assertEqual(transaction.state, "sent")
        payload = send_mock.call_args.args[0]
        code = payload["receivers"][0]["customParams"][0]["value"]
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())
        self.assertNotEqual(transaction.code_hash, code)
        self.assertNotIn(code, transaction.provider_excerpt or "")
        self.assertTrue(transaction.phone_masked.endswith("0222"))
        self.assertNotIn("966500000222", transaction.phone_masked)

        ok, message = transaction.verify_code(code)
        self.assertTrue(ok, message)
        self.assertEqual(transaction.state, "verified")
        self.assertTrue(transaction.verified_at)

    def test_wrong_code_counts_attempts_and_locks_transaction(self):
        flow = self._flow(max_attempts=2)
        response = Mock(text="accepted", reason="OK")
        with patch.object(
            otp_flow_module.WatiIdempotency,
            "acquire_durable",
            return_value=True,
        ), patch.object(
            otp_flow_module.WatiClient,
            "send_template_messages",
            return_value=response,
        ):
            transaction = flow.request_otp(self.partner)

        ok, _message = transaction.verify_code("111111")
        self.assertFalse(ok)
        self.assertEqual(transaction.attempt_count, 1)
        self.assertEqual(transaction.state, "sent")

        ok, _message = transaction.verify_code("222222")
        self.assertFalse(ok)
        self.assertEqual(transaction.attempt_count, 2)
        self.assertEqual(transaction.state, "locked")

    def test_request_cancels_previous_active_code_for_same_service_record(self):
        flow = self._flow()
        response = Mock(text="accepted", reason="OK")
        with patch.object(
            otp_flow_module.WatiIdempotency,
            "acquire_durable",
            return_value=True,
        ), patch.object(
            otp_flow_module.WatiClient,
            "send_template_messages",
            return_value=response,
        ):
            first = flow.request_otp(self.partner)
            second = flow.request_otp(self.partner)

        self.assertEqual(first.state, "cancelled")
        self.assertEqual(second.state, "sent")
        self.assertNotEqual(first.code_hash, second.code_hash)
