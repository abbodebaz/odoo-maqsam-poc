from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestTemplateProviderPolicy(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Template = self.env["wati.template"].sudo()

    def test_imported_provider_name_is_preserved_even_if_not_locally_authorable(self):
        template = self.Template.create(
            {
                "name": "Legacy-Template Name",
                "language": "en",
                "category": "UTILITY",
                "body": "Provider snapshot",
                "source": "wati",
                "status": "approved",
            }
        )
        self.assertEqual(template.name, "Legacy-Template Name")
        self.assertEqual(template.source, "wati")

    def test_imported_provider_placeholder_contract_is_not_revalidated(self):
        template = self.Template.create(
            {
                "name": "legacy_provider_template",
                "language": "en",
                "category": "UTILITY",
                "body": "Hello {{1}} {{name}}",
                "source": "wati",
                "status": "approved",
            }
        )
        self.assertEqual(template.body, "Hello {{1}} {{name}}")

    def test_local_authoring_rules_remain_strict(self):
        with self.assertRaises(ValidationError):
            self.Template.create(
                {
                    "name": "Bad Local Name",
                    "language": "en",
                    "category": "UTILITY",
                    "body": "Hello",
                    "source": "odoo",
                }
            )

    def test_authoring_onchange_formats_spaces_and_dashes_only(self):
        template = self.Template.new(
            {
                "name": "Order Ready-AR",
                "language": "ar",
                "category": "UTILITY",
                "body": "مرحبًا",
                "source": "odoo",
                "status": "draft",
            }
        )
        template._onchange_name_authoring_helper()
        self.assertEqual(template.name, "order_ready_ar")
