from odoo.tests.common import TransactionCase

from ..services.template_catalog import normalize_template


class TestWatiTemplateCustomParamsContract(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Template = self.env["wati.template"].sudo()

    def test_submission_uses_wati_param_name_and_value_contract(self):
        template = self.Template.create(
            {
                "name": "marketing_variable_contract",
                "language": "ar",
                "category": "MARKETING",
                "body": "مرحبًا {{name}}، عندنا عرض خاص لك.",
                "builder_button_type": "URL",
                "builder_button_text": "شاهد العرض",
                "builder_button_url": "https://baytalebaa.com/",
            }
        )
        variable = template.variable_ids.filtered(lambda row: row.name == "name")
        variable.sample_value = "أحمد"

        payload = template._build_submission_payload()

        self.assertEqual(
            payload["customParams"],
            [{"paramName": "name", "paramValue": "أحمد"}],
        )
        self.assertNotIn("name", payload["customParams"][0])
        self.assertNotIn("value", payload["customParams"][0])
        self.assertEqual(payload["buttonsType"], "call_to_action")
        self.assertEqual(
            payload["buttons"][0]["parameter"]["url"],
            "https://baytalebaa.com/",
        )

    def test_provider_param_name_round_trips_into_normalized_template(self):
        normalized = normalize_template(
            {
                "elementName": "approved_variable_template",
                "language": {"key": "Arabic", "value": "ar", "text": "Arabic"},
                "status": "APPROVED",
                "body": "مرحبًا {{1}}",
                "bodyOriginal": "مرحبًا {{name}}",
                "customParams": [
                    {"paramName": "name", "paramValue": "أحمد"},
                ],
            }
        )

        self.assertEqual(normalized["custom_params"], ["name"])
        self.assertEqual(normalized["status"], "approved")
