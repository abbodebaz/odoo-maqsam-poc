from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ..services.client import WatiClient
from ..services.exceptions import WatiRequestError


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class TestWatiTemplateProviderError(TransactionCase):

    def test_creation_message_validation_error_is_rejected(self):
        client = object.__new__(WatiClient)
        response = _FakeResponse(
            {"message": "Button parameter is null, please check the template."}
        )
        with self.assertRaises(WatiRequestError):
            client._ensure_template_creation_ack(response)

    def test_neutral_creation_message_is_left_for_catalogue_verification(self):
        client = object.__new__(WatiClient)
        response = _FakeResponse({"message": "Template request received"})
        self.assertIs(client._ensure_template_creation_ack(response), response)

    def test_button_submission_fails_closed_until_provider_contract_is_verified(self):
        template = self.env["wati.template"].sudo().create(
            {
                "name": "button_guard_test",
                "language": "ar",
                "category": "UTILITY",
                "body": "مرحبًا",
                "builder_button_type": "QUICK_REPLY",
                "builder_button_text": "تم",
            }
        )
        with self.assertRaises(UserError):
            template._assert_can_submit()

    def test_known_provider_rejection_returns_unverified_record_to_draft(self):
        template = self.env["wati.template"].sudo().create(
            {
                "name": "provider_reject_test",
                "language": "ar",
                "category": "UTILITY",
                "body": "مرحبًا",
            }
        )
        template.write(
            {
                "status": "pending_internal",
                "provider_response": '{"message":"Button parameter is null, please check the template."}',
            }
        )
        repaired = self.env["wati.template"].sudo()._repair_provider_rejected_template_submissions()
        self.assertGreaterEqual(repaired, 1)
        self.assertEqual(template.status, "draft")
        self.assertIn("Button parameter is null", template.last_error)
