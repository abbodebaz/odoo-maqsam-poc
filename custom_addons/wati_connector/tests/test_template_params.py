from odoo.tests.common import TransactionCase

from ..models.wati_automation_template_truth import _canonical_template_param_names


class TestWatiTemplateParams(TransactionCase):
    def test_matching_custom_params_label_positional_body_variables(self):
        template = {
            "body": "نوع الخدمة: {{1}}\nالتاريخ: {{2}}\nالوقت: {{3}}",
            "customParams": [
                {"name": "services"},
                {"name": "serdate"},
                {"name": "sertime"},
            ],
        }
        self.assertEqual(
            _canonical_template_param_names(template),
            ["services", "serdate", "sertime"],
        )

    def test_mismatched_metadata_is_ignored_when_body_has_one_variable(self):
        template = {
            "body": "مرحبًا {{1}}، كيف نقدر نخدمك؟",
            "customParams": [
                {"name": "services"},
                {"name": "serdate"},
                {"name": "sertime"},
            ],
        }
        self.assertEqual(_canonical_template_param_names(template), ["1"])

    def test_positional_body_params_work_without_metadata(self):
        template = {"body": "مرحبًا {{1}}، موعدك {{2}}"}
        self.assertEqual(_canonical_template_param_names(template), ["1", "2"])

    def test_named_body_params_are_authoritative(self):
        template = {
            "body": "مرحبًا {{customer_name}}، موعدك {{appointment_date}}",
            "customParams": [
                {"name": "old_name"},
                {"name": "old_date"},
                {"name": "extra"},
            ],
        }
        self.assertEqual(
            _canonical_template_param_names(template),
            ["customer_name", "appointment_date"],
        )
