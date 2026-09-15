from odoo.tests.common import TransactionCase

from ..models.wati_automation_response_fix import (
    _truthy_collection,
    _wati_payload_has_hard_failure,
)


class TestWatiResponseTruth(TransactionCase):
    def test_nested_empty_errors_are_not_failure(self):
        payload = {
            "result": False,
            "errors": {
                "error": "",
                "invalidWhatsappNumbers": [],
                "invalidCustomParameters": [],
            },
        }
        self.assertFalse(_truthy_collection(payload["errors"]))
        self.assertFalse(_wati_payload_has_hard_failure(payload))

    def test_invalid_recipient_is_failure(self):
        payload = {
            "result": False,
            "errors": {
                "error": "",
                "invalidWhatsappNumbers": ["966500000000"],
                "invalidCustomParameters": [],
            },
        }
        self.assertTrue(_wati_payload_has_hard_failure(payload))

    def test_non_empty_error_text_is_failure(self):
        payload = {
            "result": False,
            "errors": {
                "error": "Template is not approved",
                "invalidWhatsappNumbers": [],
                "invalidCustomParameters": [],
            },
        }
        self.assertTrue(_wati_payload_has_hard_failure(payload))
