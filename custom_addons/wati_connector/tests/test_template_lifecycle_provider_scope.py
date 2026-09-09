import json

from odoo.tests.common import TransactionCase


class TestWatiTemplateLifecycleProviderScope(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Template = self.env["wati.template"].sudo()
        self.template = self.Template.create(
            {
                "name": "scope_rejected_test",
                "language": "ar",
                "category": "UTILITY",
                "body": "مرحبًا {{name}}",
            }
        )
        self.template.variable_ids.sample_value = "أحمد"
        self.template.write({"status": "pending_internal"})

    def test_webhook_audit_recovers_wrapped_rejected_state(self):
        payload = {
            "data": {
                "eventType": "templateReviewed",
                "templateName": "scope_rejected_test",
                "templateId": "meta-scope-1",
                "watiTemplateId": "wati-scope-1",
                "newTemplateStatus": 3,
                "rejectionReason": "Provider policy rejection",
            }
        }
        self.env["wati.webhook.event"].sudo().create(
            {
                "event_type": "event",
                "payload": json.dumps(payload),
            }
        )

        normalized = self.template._find_lifecycle_from_webhook_audit()

        self.assertTrue(normalized)
        self.assertEqual(normalized["status"], "rejected")
        self.assertEqual(normalized["rejection_reason"], "Provider policy rejection")
        self.assertEqual(normalized["meta_template_id"], "meta-scope-1")
        self.assertEqual(normalized["wati_template_id"], "wati-scope-1")

    def test_provider_summary_excludes_message_body(self):
        summary = self.template._safe_remote_summary(
            {
                "elementName": "scope_rejected_test",
                "status": 3,
                "body": "sensitive body",
                "customParams": [{"name": "customer"}],
                "templateId": "meta-scope-2",
            }
        )
        self.assertEqual(summary["elementName"], "scope_rejected_test")
        self.assertEqual(summary["status"], 3)
        self.assertEqual(summary["templateId"], "meta-scope-2")
        self.assertNotIn("body", summary)
        self.assertNotIn("customParams", summary)
