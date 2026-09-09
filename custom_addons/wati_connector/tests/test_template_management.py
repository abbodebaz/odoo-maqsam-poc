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
