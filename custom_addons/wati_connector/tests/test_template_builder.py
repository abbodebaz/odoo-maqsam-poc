from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestWatiTemplateBuilder(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Template = self.env["wati.template"].sudo()

    def _draft(self, **extra):
        values = {
            "name": "builder_test",
            "language": "en",
            "category": "UTILITY",
            "body": "Hello {{name}}",
        }
        values.update(extra)
        template = self.Template.create(values)
        template.variable_ids.sample_value = "John"
        return template

    def test_standard_text_header_and_url_button_payload(self):
        template = self._draft(
            builder_header_type="TEXT",
            builder_header_text="Order update",
            builder_button_type="URL",
            builder_button_text="Open order",
            builder_button_url="https://example.com/order/1",
        )

        payload = template._build_submission_payload()
        self.assertEqual(payload["subCategory"], "STANDARD")
        self.assertEqual(
            payload["header"],
            {"type": "Text", "text": "Order update"},
        )
        self.assertEqual(payload["buttonsType"], "call_to_action")
        self.assertEqual(
            payload["buttons"],
            [
                {
                    "type": "url",
                    "text": "Open order",
                    "url": "https://example.com/order/1",
                }
            ],
        )

    def test_media_header_payload(self):
        template = self._draft(
            builder_header_type="DOCUMENT",
            header_media_url="https://example.com/invoice.pdf",
            header_media_filename="invoice.pdf",
        )
        payload = template._build_submission_payload()
        self.assertEqual(
            payload["header"],
            {
                "type": "Document",
                "media": {
                    "url": "https://example.com/invoice.pdf",
                    "fileName": "invoice.pdf",
                },
            },
        )

    def test_quick_reply_payload(self):
        template = self._draft(
            builder_button_type="QUICK_REPLY",
            builder_button_text="Confirm",
        )
        payload = template._build_submission_payload()
        self.assertEqual(payload["buttonsType"], "quick_reply")
        self.assertEqual(
            payload["buttons"],
            [{"type": "quick_reply", "text": "Confirm"}],
        )

    def test_advanced_kind_is_selectable_but_safe_to_submit(self):
        template = self._draft(template_kind="CAROUSEL")
        self.assertEqual(template.template_kind, "CAROUSEL")
        self.assertEqual(template.sub_category, "CAROUSEL")
        self.assertTrue(template.advanced_kind_notice)
        with self.assertRaises(UserError):
            template._assert_can_submit()

    def test_imported_values_populate_builder_controls(self):
        values = self.Template._remote_values(
            {
                "category": "MARKETING",
                "sub_category": "CAROUSEL",
                "status": "approved",
                "quality": "green",
                "body": "Hello",
                "footer": "Footer",
                "header_type": "IMAGE",
                "header_text": "",
                "buttons": [
                    {
                        "type": "url",
                        "text": "Open",
                        "url": "https://example.com",
                    }
                ],
                "buttons_json": "[]",
                "wati_template_id": "w-1",
                "meta_template_id": "m-1",
                "waba_id": "b-1",
                "channel_phone_number": "966500000000",
                "raw": {},
            }
        )
        self.assertEqual(values["template_kind"], "CAROUSEL")
        self.assertEqual(values["builder_header_type"], "IMAGE")
        self.assertEqual(values["builder_button_type"], "URL")
        self.assertEqual(values["builder_button_text"], "Open")
        self.assertEqual(values["builder_button_url"], "https://example.com")
