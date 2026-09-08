from odoo.tests.common import TransactionCase

from ..models.wati_automation_improvements import _template_param_names


class TestWatiTemplateParams(TransactionCase):
    def test_custom_params_replace_positional_body_aliases(self):
        template = {
            "body": "نوع الخدمة: {{1}}\nالتاريخ: {{2}}\nالوقت: {{3}}",
            "customParams": [
                {"name": "services"},
                {"name": "serdate"},
                {"name": "sertime"},
            ],
        }
        self.assertEqual(
            _template_param_names(template),
            ["services", "serdate", "sertime"],
        )

    def test_positional_body_params_work_without_metadata(self):
        template = {"body": "مرحبًا {{1}}، موعدك {{2}}"}
        self.assertEqual(_template_param_names(template), ["1", "2"])

    def test_named_body_params_are_kept_without_duplicates(self):
        template = {
            "body": "مرحبًا {{customer_name}}، موعدك {{appointment_date}}",
            "customParams": [
                {"name": "customer_name"},
                {"name": "appointment_date"},
            ],
        }
        self.assertEqual(
            _template_param_names(template),
            ["customer_name", "appointment_date"],
        )
