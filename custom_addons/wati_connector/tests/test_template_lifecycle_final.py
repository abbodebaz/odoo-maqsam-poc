from unittest.mock import patch

from odoo.tests.common import TransactionCase

from ..models import wati_template_lifecycle_final as lifecycle_module


class _JsonResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class TestWatiTemplateLifecycleFinal(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Template = self.env["wati.template"].sudo()
        self.template = self.Template.create(
            {
                "name": "order_ready_final",
                "language": "ar",
                "category": "UTILITY",
                "body": "مرحبًا {{name}}",
            }
        )
        self.template.variable_ids.sample_value = "أحمد"

    def test_language_identity_accepts_provider_arabic_variants(self):
        self.assertTrue(
            self.template._remote_identity_match(
                {"name": "order_ready_final", "language": "Arabic"}
            )
        )
        self.assertTrue(
            self.template._remote_identity_match(
                {"name": "order_ready_final", "language": "ar-SA"}
            )
        )
        self.assertFalse(
            self.template._remote_identity_match(
                {"name": "order_ready_final", "language": "en"}
            )
        )

    def test_v2_exact_name_lookup_finds_rejected_template(self):
        calls = []

        class FakeClient:
            def __init__(self, env):
                self.env = env

            def get(self, path, **kwargs):
                calls.append((path, kwargs))
                return _JsonResponse(
                    {
                        "messageTemplates": [
                            {
                                "elementName": "order_ready_final",
                                "language": "Arabic",
                                "category": "UTILITY",
                                "status": 3,
                                "body": "مرحبًا {{name}}",
                                "customParams": [{"name": "name"}],
                                "templateId": "meta-final-1",
                                "watiTemplateId": "wati-final-1",
                                "rejectionReason": "Sample rejection reason",
                            }
                        ]
                    }
                )

        with patch.object(lifecycle_module, "WatiClient", FakeClient):
            normalized = self.template._fetch_exact_remote_submission_v2()

        self.assertTrue(normalized)
        self.assertEqual(normalized["status"], "rejected")
        self.assertEqual(normalized["rejection_reason"], "Sample rejection reason")
        self.assertEqual(calls[0][0], "api/v2/getMessageTemplates")
        self.assertEqual(calls[0][1]["params"]["name"], "order_ready_final")

    def test_rejected_template_always_has_user_visible_reason(self):
        normalized = {
            "name": "order_ready_final",
            "language": "ar",
            "category": "UTILITY",
            "sub_category": "STANDARD",
            "status": "rejected",
            "quality": "unknown",
            "body": "مرحبًا {{name}}",
            "footer": "",
            "header_type": "",
            "header_text": "",
            "buttons_json": "[]",
            "custom_params": ["name"],
            "wati_template_id": "wati-final-2",
            "meta_template_id": "meta-final-2",
            "waba_id": "",
            "channel_phone_number": "",
            "rejection_reason": "",
            "raw": {},
        }
        self.template._apply_lifecycle_remote(normalized, reason="test")

        self.assertEqual(self.template.status, "rejected")
        self.assertTrue(self.template.rejection_reason)
        self.assertIn("WATI", self.template.rejection_reason)
        self.assertFalse(self.template.last_error)

    def test_lifecycle_poller_is_installed(self):
        cron = self.env.ref("wati_connector.ir_cron_wati_template_lifecycle_refresh")
        self.assertTrue(cron.active)
        self.assertEqual(cron.interval_number, 5)
        self.assertEqual(cron.interval_type, "minutes")
