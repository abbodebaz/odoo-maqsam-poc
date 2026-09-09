from odoo.tests.common import TransactionCase


class TestWatiTemplateSubmissionTruth(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Template = self.env["wati.template"].sudo()

    def test_unverified_legacy_pending_state_is_repaired(self):
        template = self.Template.create(
            {
                "name": "order_ready_test_truth",
                "language": "ar",
                "category": "UTILITY",
                "body": "مرحبًا {{name}}",
            }
        )
        template.variable_ids.sample_value = "أحمد"
        template.write(
            {
                "status": "pending",
                "last_error": "لم يظهر هذا القالب في نتيجة WATI الحالية.",
                "wati_template_id": False,
                "meta_template_id": False,
            }
        )

        self.Template._repair_unverified_submissions()

        self.assertEqual(template.status, "pending_internal")
        self.assertIn("قيد التحقق", template.last_error)

    def test_remote_identity_requires_exact_name_and_language(self):
        template = self.Template.create(
            {
                "name": "identity_check",
                "language": "ar",
                "category": "UTILITY",
                "body": "مرحبًا",
            }
        )
        self.assertTrue(
            template._remote_identity_match(
                {"name": "identity_check", "language": "ar"}
            )
        )
        self.assertFalse(
            template._remote_identity_match(
                {"name": "identity_check", "language": "en"}
            )
        )
        self.assertFalse(
            template._remote_identity_match(
                {"name": "other_template", "language": "ar"}
            )
        )
