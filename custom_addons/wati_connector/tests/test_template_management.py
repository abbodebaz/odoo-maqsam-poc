import json

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from ..services.template_catalog import (
    normalize_quality,
    normalize_status,
    normalize_template,
)


class TestWatiTemplateCatalog(TransactionCase):

    def test_normalize_provider_status_and_quality_codes(self):
        self.assertEqual(normalize_status(0), "draft")
        self.assertEqual(normalize_status(1), "pending")
        self.assertEqual(normalize_status(2), "approved")
        self.assertEqual(normalize_status(7), "paused")
        self.assertEqual(normalize_quality(1), "green")
        self.assertEqual(normalize_quality(2), "red")
        self.assertEqual(normalize_quality(3), "yellow")

    def test_normalize_remote_template_keeps_api_parameter_names(self):
        item = {
            "elementName": "order_ready",
            "language": "ar",
            "category": "UTILITY",
            "subCategory": "STANDARD",
            "status": 2,
            "quality": 1,
            "body": "مرحبا {{1}}، طلبك جاهز",
            "customParams": [{"name": "customer_name"}],
            "templateId": "meta-1",
            "watiTemplateId": "wati-1",
            "wabaId": "waba-1",
        }
        normalized = normalize_template(item)
        self.assertEqual(normalized["name"], "order_ready")
        self.assertEqual(normalized["status"], "approved")
        self.assertEqual(normalized["quality"], "green")
        self.assertEqual(normalized["custom_params"], ["customer_name"])
        self.assertEqual(normalized["meta_template_id"], "meta-1")
        self.assertEqual(normalized["wati_template_id"], "wati-1")

    def test_normalize_wati_v2_language_object_uses_machine_value(self):
        normalized = normalize_template(
            {
                "elementName": "order_ready_test",
                "language": {"key": "Arabic", "value": "ar", "text": "Arabic"},
                "status": "REJECTED",
                "wabaId": "324395694078934",
            }
        )
        self.assertEqual(normalized["language"], "ar")
        self.assertEqual(normalized["status"], "rejected")
        self.assertEqual(normalized["waba_id"], "324395694078934")


class TestWatiTemplateModel(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Template = self.env["wati.template"].sudo()

    def test_draft_auto_builds_variables_and_submission_payload(self):
        template = self.Template.create(
            {
                "name": "order_ready_ar",
                "language": "ar",
                "category": "UTILITY",
                "body": "مرحبًا {{name}}، طلبك رقم {{order_id}} جاهز.",
                "footer": "شكرًا لاستخدامك خدمتنا",
            }
        )
        self.assertEqual(template.variable_ids.mapped("name"), ["name", "order_id"])
        template.variable_ids.filtered(lambda row: row.name == "name").sample_value = "أحمد"
        template.variable_ids.filtered(lambda row: row.name == "order_id").sample_value = "SO-1001"

        payload = template._build_submission_payload()
        self.assertEqual(payload["type"], "template")
        self.assertEqual(payload["category"], "UTILITY")
        self.assertEqual(payload["subCategory"], "STANDARD")
        self.assertEqual(payload["buttonsType"], "NONE")
        self.assertEqual(payload["elementName"], "order_ready_ar")
        self.assertEqual(
            payload["customParams"],
            [
                {"name": "name", "value": "أحمد"},
                {"name": "order_id", "value": "SO-1001"},
            ],
        )
        self.assertIn("أحمد", template.preview_text)
        self.assertIn("SO-1001", template.preview_text)

    def test_static_url_button_uses_provider_parameter_contract(self):
        template = self.Template.create(
            {
                "name": "marketing_url_button",
                "language": "ar",
                "category": "MARKETING",
                "body": "اكتشف العرض الجديد",
                "builder_button_type": "URL",
                "builder_button_text": "اكتشف العرض",
                "builder_button_url": "example.com",
            }
        )
        payload = template._build_submission_payload()
        self.assertEqual(payload["buttonsType"], "call_to_action")
        self.assertEqual(payload["buttons"][0]["type"], "url")
        self.assertEqual(payload["buttons"][0]["parameter"]["text"], "اكتشف العرض")
        self.assertEqual(payload["buttons"][0]["parameter"]["url"], "https://example.com")
        self.assertEqual(payload["buttons"][0]["parameter"]["urlType"], "static")
        self.assertEqual(template.builder_button_url, "https://example.com")

    def test_button_snapshot_refreshes_when_url_is_written_later(self):
        template = self.Template.create(
            {
                "name": "marketing_url_late",
                "language": "ar",
                "category": "MARKETING",
                "body": "شاهد العرض",
                "builder_button_type": "URL",
                "builder_button_text": "شاهد العرض",
            }
        )
        template.write({"builder_button_url": "example.com/offers"})
        snapshot = json.loads(template.buttons_json)
        self.assertEqual(snapshot[0]["parameter"]["url"], "https://example.com/offers")
        self.assertEqual(template.builder_button_url, "https://example.com/offers")

    def test_quick_reply_button_uses_provider_parameter_contract(self):
        template = self.Template.create(
            {
                "name": "marketing_quick_reply",
                "language": "ar",
                "category": "MARKETING",
                "body": "هل ترغب بمعرفة المزيد؟",
                "builder_button_type": "QUICK_REPLY",
                "builder_button_text": "نعم",
            }
        )
        payload = template._build_submission_payload()
        self.assertEqual(payload["buttonsType"], "quick_reply")
        self.assertEqual(payload["buttons"][0]["type"], "quick_reply")
        self.assertEqual(payload["buttons"][0]["parameter"]["text"], "نعم")
        self.assertIsNone(payload["buttons"][0]["parameter"]["url"])

    def test_phone_button_uses_provider_parameter_contract(self):
        template = self.Template.create(
            {
                "name": "marketing_call_button",
                "language": "ar",
                "category": "MARKETING",
                "body": "تواصل معنا",
                "builder_button_type": "PHONE",
                "builder_button_text": "اتصل الآن",
                "builder_button_phone": "+966500000000",
            }
        )
        payload = template._build_submission_payload()
        self.assertEqual(payload["buttonsType"], "call_to_action")
        self.assertEqual(payload["buttons"][0]["type"], "call")
        self.assertEqual(
            payload["buttons"][0]["parameter"]["phoneNumber"],
            "+966500000000",
        )

    def test_remote_nested_button_parameter_populates_builder_fields(self):
        values = self.Template._remote_values(
            {
                "buttons": [
                    {
                        "type": "url",
                        "parameter": {
                            "text": "شاهد العرض",
                            "url": "https://example.com/offers",
                            "urlType": "static",
                        },
                    }
                ]
            }
        )
        self.assertEqual(values["builder_button_type"], "URL")
        self.assertEqual(values["builder_button_text"], "شاهد العرض")
        self.assertEqual(values["builder_button_url"], "https://example.com/offers")

    def test_mixed_named_and_positional_variables_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.Template.create(
                {
                    "name": "invalid_mix",
                    "language": "ar",
                    "category": "UTILITY",
                    "body": "مرحبًا {{1}} يا {{name}}",
                }
            )

    def test_invalid_template_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.Template.create(
                {
                    "name": "Bad Name",
                    "language": "ar",
                    "category": "UTILITY",
                    "body": "مرحبًا",
                }
            )

    def test_template_review_webhook_updates_status_and_identifiers(self):
        template = self.Template.create(
            {
                "name": "review_me",
                "language": "ar",
                "category": "UTILITY",
                "body": "مرحبًا",
            }
        )
        template.write({"status": "pending"})
        handled = template.apply_template_webhook(
            {
                "eventType": "templateReviewed",
                "wabaId": "waba-100",
                "templateName": "review_me",
                "templateId": "meta-100",
                "watiTemplateId": "wati-100",
                "oldTemplateStatus": 1,
                "newTemplateStatus": 2,
                "channelPhoneNumber": "966500000000",
            }
        )
        self.assertTrue(handled)
        self.assertEqual(template.status, "approved")
        self.assertEqual(template.meta_template_id, "meta-100")
        self.assertEqual(template.wati_template_id, "wati-100")
        self.assertEqual(template.waba_id, "waba-100")
        self.assertEqual(template.channel_phone_number, "966500000000")

    def test_quality_and_category_webhooks_are_independent(self):
        template = self.Template.create(
            {
                "name": "quality_template",
                "language": "ar",
                "category": "UTILITY",
                "body": "مرحبًا",
            }
        )
        template.write(
            {
                "status": "approved",
                "meta_template_id": "meta-q",
                "wati_template_id": "wati-q",
            }
        )
        template.apply_template_webhook(
            {
                "eventType": "templateQualityUpdated",
                "templateId": "meta-q",
                "watiTemplateId": "wati-q",
                "templateName": "quality_template",
                "newTemplateQuality": 3,
            }
        )
        self.assertEqual(template.quality, "yellow")
        self.assertEqual(template.status, "approved")

        template.apply_template_webhook(
            {
                "eventType": "templateCategoryUpdated",
                "templateId": "meta-q",
                "watiTemplateId": "wati-q",
                "templateName": "quality_template",
                "newTemplateCategory": "MARKETING",
            }
        )
        self.assertEqual(template.category, "MARKETING")
        self.assertEqual(template.status, "approved")
