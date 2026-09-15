from odoo.tests.common import TransactionCase


class TestWatiSmartTarget(TransactionCase):
    def test_many2one_metadata_uses_related_records(self):
        rule_model = self.env["wati.automation.rule"]
        field = self.env["ir.model.fields"]._get("res.partner", "country_id")

        metadata = rule_model._smart_target_metadata_for_field(field)

        self.assertIn(metadata["mode"], ("suggest", "input"))
        self.assertEqual(metadata["field_type"], "many2one")
        self.assertEqual(metadata.get("relation"), "res.country")

    def test_selection_metadata_is_select(self):
        rule_model = self.env["wati.automation.rule"]
        field = self.env["ir.model.fields"]._get("res.partner", "company_type")

        metadata = rule_model._smart_target_metadata_for_field(field)

        self.assertEqual(metadata["mode"], "select")
        self.assertEqual(metadata["field_type"], "selection")
        self.assertTrue(metadata["options"])
